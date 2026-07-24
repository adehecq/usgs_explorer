"""
Description: Download pipeline for USGS scenes.

Architecture:
  SceneDownloader (orchestrator)
  ├── ProductSelector  — pick which product to download from raw API options
  ├── LinkResolver     — convert products → download URLs (handles polling)
  ├── FileDownloader   — parallel HTTP download, no M2M knowledge
  └── FileExtractor    — decompress .tar.gz / .gz archives

Last modified: 2026
Author: Luc Godin
"""

from __future__ import annotations

import datetime
import gzip
import signal
import sys
import tarfile
import threading
import time
from collections.abc import Generator, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from shutil import copyfileobj
from typing import TYPE_CHECKING

import requests
from tqdm import tqdm

import usgsxplore.errors as err

if TYPE_CHECKING:
    from usgsxplore.api import API


@dataclass
class DownloadProduct:
    """Selected product, ready to be requested from the API."""

    entity_id: str
    product_id: str  # passed as productId to download-request
    product_name: str
    filesize: int


@dataclass
class DownloadLink:
    """URL ready to be downloaded."""

    entity_id: str
    url: str
    filesize: int


class ProductSelector:
    """
    From the raw response of the "download-options" endpoint, select a product
    code and return typed DownloadProduct objects.

    Pure logic — no I/O, fully unit-testable without any mock.
    """

    def select(
        self,
        options: list[dict],
        product_number: int | None = None,
    ) -> list[DownloadProduct]:
        """
        Filter and select download options based on availability and product choice.

        The first available entity is used as a reference to list all product
        variants (e.g. "Level-1", "Level-2 SR", …). The chosen productCode is
        then applied to every entity in *options*.

        :param options: Raw list of dicts from the download-options endpoint.
        :param product_number: Index of the product to select when several exist.
            If None and multiple products are available, raises DownloadOptionsError.
        :return: List of DownloadProduct for the selected product code.
        :raises DownloadOptionsError: If no product is available, or the selection
            is ambiguous or out of range.
        """
        available = [o for o in options if o.get("available")]
        if not available:
            raise err.DownloadOptionsError("No product available")

        # Use the first entity as reference to enumerate product variants
        ref_entity = available[0]["entityId"]
        product_variants = [o for o in available if o["entityId"] == ref_entity]

        if len(product_variants) > 1:
            if product_number is None:
                names = "\n".join(f"  {i}: {p['productName']}" for i, p in enumerate(product_variants))
                raise err.DownloadOptionsError(
                    f"Multiple products available, choose one with --product-number:\n{names}"
                )
            if not (0 <= product_number < len(product_variants)):
                names = "\n".join(f"  {i}: {p['productName']}" for i, p in enumerate(product_variants))
                raise err.DownloadOptionsError(f"Invalid product_number {product_number}, valid choices:\n{names}")
            selected_code = product_variants[product_number]["productCode"]
        else:
            selected_code = product_variants[0]["productCode"]

        return [
            DownloadProduct(
                entity_id=o["entityId"],
                product_id=o["id"],
                product_name=o["productName"],
                filesize=o.get("filesize", 0),
            )
            for o in available
            if o["productCode"] == selected_code
        ]


class LinkResolver:
    """
    Sends "download-request" then polls "download-retrieve" until every link is
    available. Yields DownloadLink objects as they become ready — callers start
    downloading immediately without waiting for the whole batch.
    """

    def __init__(self, api: API, max_retries: int = 100, retry_delay: int = 30):
        self.api = api
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def resolve(
        self,
        products: list[DownloadProduct],
        label: str,
    ) -> Generator[DownloadLink, None, None]:
        """
        Request download URLs for *products* and yield DownloadLink objects.

        Handles "preparing" downloads by polling download-retrieve until all
        links are ready or *max_retries* is exhausted.

        :param products: Products to request.
        :param label: Label for the download-request call (used to track/clean up).
        :raises USGSError: If downloads don't become available within max_retries.
        """
        download_list = [{"entityId": p.entity_id, "productId": p.product_id} for p in products]
        filesizes = {p.entity_id: p.filesize for p in products}
        n_requested = len(download_list)

        result = self.api.request(
            "download-request",
            {"downloads": download_list, "label": label},
        )

        n_failed = len(result.get("failed", []))
        valid_ids = set(result.get("newRecords", [])) | set(result.get("duplicateProducts", []))

        if result.get("preparingDownloads"):
            yielded_ids: list[int] = []

            # Yield whatever is already available
            retrieve = self.api.request("download-retrieve", {"label": label})
            for dl in retrieve.get("available", []) + retrieve.get("requested", []):
                if str(dl["downloadId"]) in valid_ids:
                    yielded_ids.append(dl["downloadId"])
                    yield DownloadLink(
                        entity_id=dl["entityId"],
                        url=dl["url"],
                        filesize=filesizes.get(dl["entityId"], 0),
                    )

            # Poll until everything is ready
            attempts = 0
            while len(yielded_ids) < n_requested - n_failed:
                if attempts >= self.max_retries:
                    n_missing = n_requested - n_failed - len(yielded_ids)
                    raise err.USGSError(f"{n_missing} download(s) not available after {self.max_retries} retries.")
                n_pending = n_requested - n_failed - len(yielded_ids)
                print(
                    f"{n_pending} download(s) not yet available, "
                    f"retrying in {self.retry_delay}s "
                    f"({attempts + 1}/{self.max_retries})..."
                )
                time.sleep(self.retry_delay)
                attempts += 1
                retrieve = self.api.request("download-retrieve", {"label": label})
                for dl in retrieve.get("available", []):
                    if dl["downloadId"] not in yielded_ids and str(dl["downloadId"]) in valid_ids:
                        yielded_ids.append(dl["downloadId"])
                        yield DownloadLink(
                            entity_id=dl["entityId"],
                            url=dl["url"],
                            filesize=filesizes.get(dl["entityId"], 0),
                        )
        else:
            for dl in result.get("availableDownloads", []):
                yield DownloadLink(
                    entity_id=dl["entityId"],
                    url=dl["url"],
                    filesize=filesizes.get(dl["entityId"], 0),
                )


class FileDownloader:
    """
    Downloads DownloadLink objects in parallel to an output directory.
    Has no knowledge of the M2M API — independently testable with any URL.
    """

    def __init__(self, max_workers: int = 4, show_progress: bool = True):
        self.max_workers = max_workers
        self.show_progress = show_progress

    def download(
        self,
        links: Iterable[DownloadLink],
        output_dir: Path,
    ) -> list[Path]:
        """
        Download all links in parallel, one tqdm bar per active worker slot.

        Links are consumed lazily: as the generator yields new links (which may
        involve API polling), they are submitted to the thread pool immediately
        so workers never sit idle unnecessarily.

        :param links: Iterable of DownloadLink (may be a lazy generator).
        :param output_dir: Directory where files are saved.
        :return: List of paths of successfully downloaded files.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # One tqdm position slot per worker
        position_pool: Queue[int] = Queue()
        for i in range(self.max_workers):
            position_pool.put(i)

        stop_event = threading.Event()
        results: list[Path] = []
        lock = threading.Lock()

        def _download_one(link: DownloadLink) -> Path | None:
            pos = position_pool.get()
            bar = (
                tqdm(
                    total=link.filesize or None,
                    position=pos,
                    leave=False,
                    desc=link.entity_id[:30],
                    unit="B",
                    unit_scale=True,
                )
                if self.show_progress
                else None
            )
            try:
                with requests.get(link.url, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    cd = r.headers.get("Content-Disposition", "")
                    filename = cd.split("filename=")[1].strip('"') if "filename=" in cd else link.entity_id
                    # Rename file stem to entity_id to ensure unambiguous identification
                    filename = filename.replace(filename.split(".")[0], link.entity_id)
                    file_path = output_dir / filename
                    with open(file_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if stop_event.is_set():
                                file_path.unlink(missing_ok=True)
                                return None
                            f.write(chunk)
                            if bar:
                                bar.update(len(chunk))
                return file_path
            except Exception as e:
                print(f"\nError downloading {link.entity_id}: {e}")
                return None
            finally:
                if bar:
                    bar.close()
                position_pool.put(pos)

        def _signal_handler(sig, frame):
            print("\nDownload interrupted.")
            stop_event.set()
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for link in links:  # consume generator lazily — submits as links arrive
                futures.append(executor.submit(_download_one, link))
            for future in as_completed(futures):
                path = future.result()
                if path is not None:
                    with lock:
                        results.append(path)

        return results


class FileExtractor:
    """
    Extracts .tar.gz / .tgz / .gz archives in parallel, in-place.
    """

    def extract(
        self,
        directory: Path,
        max_workers: int = 4,
        remove_archive: bool = True,
        show_progress: bool = True,
    ) -> None:
        """
        Extract all compressed archives found in *directory*.

        :param directory: Directory containing the archives.
        :param max_workers: Number of parallel extraction threads.
        :param remove_archive: Remove the archive file after successful extraction.
        :param show_progress: Display a tqdm progress bar.
        """
        patterns = (".gz", ".tgz", ".tar.gz")
        files = [f for f in directory.iterdir() if any(f.name.lower().endswith(p) for p in patterns)]
        if not files:
            return

        def _extract_one(file_path: Path) -> str:
            try:
                if tarfile.is_tarfile(file_path):
                    with tarfile.open(file_path, "r:*") as tar:
                        tar.extractall(path=directory, filter="data")
                    if remove_archive:
                        file_path.unlink()
                    return f"Extracted archive: {file_path.name}"
                else:
                    out_path = file_path.with_suffix("")
                    with gzip.open(file_path, "rb") as f_in, open(out_path, "wb") as f_out:
                        copyfileobj(f_in, f_out)
                    if remove_archive:
                        file_path.unlink()
                    return f"Extracted file: {file_path.name}"
            except Exception as e:
                return f"Error extracting {file_path.name}: {e}"

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_extract_one, f): f for f in files}
            if show_progress:
                for _ in tqdm(as_completed(futures), total=len(futures), desc="Extracting", unit="file"):
                    pass
            else:
                for _ in as_completed(futures):
                    pass


class SceneDownloader:
    """
    Orchestrates the full download pipeline:
      options → product selection → link resolution → parallel download → extraction.

    Usage as context manager guarantees API cleanup even on error::

        with SceneDownloader(api) as dl:
            dl.download("hj2_oli_sr", entity_ids, output_dir="./data")
    """

    def __init__(
        self,
        api: API,
        selector: ProductSelector | None = None,
        resolver: LinkResolver | None = None,
        downloader: FileDownloader | None = None,
        extractor: FileExtractor | None = None,
    ):
        self.api = api
        self.selector = selector or ProductSelector()
        self.resolver = resolver or LinkResolver(api)
        self.downloader = downloader or FileDownloader()
        self.extractor = extractor or FileExtractor()

    def download(
        self,
        dataset: str,
        entity_ids: list[str],
        output_dir: str | Path = ".",
        product_number: int | None = None,
        overwrite: bool = False,
        max_workers: int = 4,
        batch_size: int = 10,
        show_progress: bool = True,
        extract: bool = True,
    ) -> None:
        """
        Download scenes identified by their entity IDs.

        :param dataset: Dataset alias (e.g. ``"hj2_oli_sr"``).
        :param entity_ids: List of entity IDs to download.
        :param output_dir: Directory where files will be saved.
        :param product_number: Index of the product when multiple are available.
            If None and multiple products exist, a DownloadOptionsError is raised.
        :param overwrite: If False, skip scenes already present in output_dir.
        :param max_workers: Number of concurrent download threads.
        :param batch_size: Number of scenes per download-request batch.
        :param show_progress: Display tqdm progress bars.
        :param extract: Extract compressed archives after download.
        """
        output_dir = Path(output_dir)
        self.downloader.max_workers = max_workers
        self.downloader.show_progress = show_progress

        entity_ids = self._filter_existing(entity_ids, output_dir, overwrite)
        if not entity_ids:
            return

        raw_options = self.api.request("download-options", {"datasetName": dataset, "entityIds": entity_ids})
        products = self.selector.select(raw_options, product_number)

        total_gb = sum(p.filesize for p in products) / 1e9
        print(f"Product   : {products[0].product_name}")
        print(f"Available : {len(products)} / {len(entity_ids)} scenes  ({total_gb:.1f} GB)")

        output_dir.mkdir(parents=True, exist_ok=True)

        for batch in _iter_batches(products, batch_size):
            self._download_batch(batch, output_dir, extract)

    def remove_all_downloads(self) -> None:
        """Remove all active downloads from the USGS API."""
        download_search = self.api.request("download-search", {"activeOnly": True})
        if not download_search:
            return
        print(f"Removing {len(download_search)} active download(s)...")
        for dl in download_search:
            self.api.request("download-remove", {"downloadId": dl["downloadId"]})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.remove_all_downloads()
        return False

    # ── private helpers ────────────────────────────────────────────────────────

    def _download_batch(
        self,
        batch: list[DownloadProduct],
        output_dir: Path,
        extract: bool,
    ) -> None:
        label = datetime.datetime.now(tz=datetime.UTC).strftime("%Y%m%d_%H%M%S")

        self.downloader.download(
            links=self.resolver.resolve(batch, label),
            output_dir=output_dir,
        )

        self.api.request("download-order-remove", {"label": label})

        if extract:
            self.extractor.extract(
                directory=output_dir,
                max_workers=self.downloader.max_workers,
                show_progress=self.downloader.show_progress,
            )

    def _filter_existing(
        self,
        entity_ids: list[str],
        output_dir: Path,
        overwrite: bool,
    ) -> list[str]:
        """Return only entity IDs not already present in output_dir."""
        if overwrite or not output_dir.exists():
            return entity_ids
        existing = {f.name for f in output_dir.iterdir()}
        filtered = [eid for eid in entity_ids if not any(n.startswith(eid) for n in existing)]
        skipped = len(entity_ids) - len(filtered)
        if skipped:
            print(f"Skipping {skipped} scene(s) already present in {output_dir}")
        return filtered


def _iter_batches(items: list, size: int) -> Generator[list, None, None]:
    """Yield successive chunks of *size* from *items*."""
    for i in range(0, len(items), size):
        yield items[i : i + size]
