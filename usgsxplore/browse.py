from abc import ABC, abstractmethod
from pathlib import Path
import numpy as np
import requests
import geopandas as gpd
from PIL import Image, UnidentifiedImageError
from io import BytesIO
from rasterio.control import GroundControlPoint
from rasterio.crs import CRS
from rasterio.transform import from_gcps
import rasterio
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed


__all__ = [
    "BrowseDownloader",
    "SaveStrategy",
    "TifSaveStrategy",
    "JpgSaveStrategy",
    "fetch_browse_img",
]

#############################################################################################
#                           STRATEGY PATTERN — SAVE BACKENDS
#############################################################################################


class SaveStrategy(ABC):
    """Abstract base class for image save strategies used by BrowseDownloader."""

    @property
    @abstractmethod
    def extension(self) -> str:
        """File extension produced by this strategy (without leading dot)."""

    @abstractmethod
    def save(self, img: np.ndarray, row: dict, output_path: Path) -> None:
        """
        Persist `img` to `output_path`.

        Parameters
        ----------
        img : np.ndarray
            Image array (H, W) for grayscale or (H, W, C) for color.
        row : dict
            Scene metadata row (may be used for georeferencing).
        output_path : Path
            Destination file path (parent directory already exists).
        """


class TifSaveStrategy(SaveStrategy):
    """
    Save a browse image as a georeferenced GeoTIFF using an affine transform
    derived from the four corner GCPs (least-squares fit).

    Requires the scene row to contain corner coordinate columns:
    `nw/ne/se/sw_corner_long_dec` and `nw/ne/se/sw_corner_lat_dec`.

    Note: an affine transform has 6 parameters; with 4 corner points the system
    is overdetermined, so one point will carry a small residual — this is expected.

    Parameters
    ----------
    crs : CRS or None, default None
        CRS for the output raster. Defaults to EPSG:4326 (WGS84).
    **creation_opts
        Rasterio creation options. Override the defaults:
        ``compress="jpeg", quality=60``.
    """

    extension = "tif"
    DEFAULT_CREATION_OPTS: dict = {"compress": "jpeg", "quality": 60}

    def __init__(self, crs: CRS | None = None, **creation_opts) -> None:
        self.crs = crs if crs is not None else CRS.from_epsg(4326)
        self.creation_opts = {**self.DEFAULT_CREATION_OPTS, **creation_opts}

    def save(self, img: np.ndarray, row: dict, output_path: Path) -> None:
        if img.ndim == 2:
            height, width = img.shape
            count = 1
            img_bands = img[np.newaxis, ...]
        else:
            height, width, count = img.shape[0], img.shape[1], img.shape[2]
            img_bands = np.moveaxis(img, -1, 0)

        gcps = [
            GroundControlPoint(row=0, col=0, x=float(row["nw_corner_long_dec"]), y=float(row["nw_corner_lat_dec"])),
            GroundControlPoint(row=0, col=width, x=float(row["ne_corner_long_dec"]), y=float(row["ne_corner_lat_dec"])),
            GroundControlPoint(
                row=height, col=width, x=float(row["se_corner_long_dec"]), y=float(row["se_corner_lat_dec"])
            ),
            GroundControlPoint(
                row=height, col=0, x=float(row["sw_corner_long_dec"]), y=float(row["sw_corner_lat_dec"])
            ),
        ]
        transform = from_gcps(gcps)

        with rasterio.open(
            output_path,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=count,
            dtype=img.dtype,
            crs=self.crs,
            transform=transform,
            **self.creation_opts,
        ) as dst:
            dst.write(img_bands)


class JpgSaveStrategy(SaveStrategy):
    """
    Save a browse image as a JPEG file (no georeferencing).

    Parameters
    ----------
    quality : int, default 60
        JPEG compression quality (1–95).
    """

    extension = "jpg"

    def __init__(self, quality: int = 60) -> None:
        self.quality = quality

    def save(self, img: np.ndarray, row: dict, output_path: Path) -> None:
        Image.fromarray(img).save(output_path, format="JPEG", quality=self.quality)


#############################################################################################
#                           DOWNLOADER
#############################################################################################


class BrowseDownloader:
    """
    Download individual browse (preview) images from a GeoDataFrame or shapefile.

    Uses a pluggable :class:`SaveStrategy` to control the output format.
    Downloads run in parallel via a thread pool.

    Parameters
    ----------
    output_dir : str or Path
        Directory where images will be saved.
    strategy : SaveStrategy
        Save backend that determines the output format. Use :class:`TifSaveStrategy`
        for georeferenced GeoTIFFs or :class:`JpgSaveStrategy` for plain JPEGs.
    url_key : str, default "browse_url"
        Column name containing browse image URLs.
    name_key : str, default "entity_id"
        Column name used to derive output filenames.
    grayscale : bool, default True
        If True, download images as grayscale.
    overwrite : bool, default False
        If True, overwrite existing files.
    max_workers : int, default 4
        Number of parallel download threads.
    show_progress : bool, default True
        If True, display a tqdm progress bar.

    Examples
    --------
    Download as georeferenced GeoTIFF:

        downloader = BrowseDownloader("output/", TifSaveStrategy())
        downloader.download("scenes.gpkg")

    Download as JPEG from a GeoDataFrame:

        downloader = BrowseDownloader("output/", JpgSaveStrategy(quality=90))
        downloader.download(gdf)
    """

    def __init__(
        self,
        output_dir: str | Path,
        strategy: SaveStrategy,
        url_key: str = "browse_url",
        name_key: str = "entity_id",
        grayscale: bool = True,
        overwrite: bool = False,
        max_workers: int = 4,
        show_progress: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.strategy = strategy
        self.url_key = url_key
        self.name_key = name_key
        self.grayscale = grayscale
        self.overwrite = overwrite
        self.max_workers = max_workers
        self.show_progress = show_progress

    def download(self, source: str | Path | gpd.GeoDataFrame) -> None:
        """
        Download browse images for all scenes in `source`.

        Parameters
        ----------
        source : str, Path, or GeoDataFrame
            Input vector file or GeoDataFrame with at least `url_key` and `name_key` columns.
        """
        if isinstance(source, (str, Path)):
            gdf = gpd.read_file(source)
        else:
            gdf = source

        self.output_dir.mkdir(parents=True, exist_ok=True)

        with requests.Session() as session:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures: dict = {}
                for _, row in gdf.iterrows():
                    name = row[self.name_key]
                    output_path = self.output_dir / f"{name}.{self.strategy.extension}"
                    if output_path.exists() and not self.overwrite:
                        continue
                    fut = executor.submit(self._download_one, row.to_dict(), output_path, session)
                    futures[fut] = name

                if self.show_progress:
                    with tqdm(total=len(futures), desc="Downloading browse images") as pbar:
                        for fut in as_completed(futures):
                            try:
                                fut.result()
                            except Exception as e:
                                print(f"Error for {futures[fut]}: {e}")
                            pbar.update(1)
                else:
                    for fut in as_completed(futures):
                        try:
                            fut.result()
                        except Exception as e:
                            print(f"Error for {futures[fut]}: {e}")

    def _download_one(self, row: dict, output_path: Path, session: requests.Session) -> None:
        img = fetch_browse_img(row[self.url_key], grayscale=self.grayscale, session=session)
        self.strategy.save(img, row, output_path)


#############################################################################################
#                           OTHER PUBLIC FUNCTIONS
#############################################################################################


def fetch_browse_img(url: str, grayscale: bool = True, session: requests.Session | None = None) -> np.ndarray:
    """
    Download a browse image from a URL and return it as a NumPy array.

    Parameters
    ----------
    url : str
        URL of the browse image.
    grayscale : bool, default True
        If True, convert the image to grayscale (single channel).
    session : requests.Session or None
        Optional session for connection pooling. Falls back to `requests` module if None.

    Returns
    -------
    np.ndarray
        Image array of shape (H, W) for grayscale or (H, W, C) for color.
    """
    client = session or requests

    try:
        response = client.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        raise requests.HTTPError(f"Failed to download image from {url}") from e

    try:
        with Image.open(BytesIO(response.content)) as img:
            if grayscale:
                img = img.convert("L")
            arr = np.array(img)
    except UnidentifiedImageError as e:
        raise ValueError(f"Failed to decode image from {url}") from e

    return arr
