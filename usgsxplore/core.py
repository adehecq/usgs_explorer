# core.py
"""
Core Python API for usgsxplore operations.
Contains pure Python functions corresponding to the CLI commands.
"""

import os
import json

from usgsxplore.api import API
from usgsxplore.filter import SceneFilter
import usgsxplore.utils as utils
from usgsxplore.browse import BrowseDownloader, TifSaveStrategy, JpgSaveStrategy
from usgsxplore.errors import FilterFieldError, FilterValueError, USGSInvalidDataset
from usgsxplore.scene_downloader import SceneDownloader

__all__ = [
    "search_scenes",
    "download_scenes",
    "download_browse_images",
    "list_datasets",
    "list_dataset_filters",
]


def search_scenes(
    dataset: str,
    username: str = None,
    token: str = None,
    output_files: list[str] | None = None,
    vector_file: str | None = None,
    location: tuple[float, float] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    clouds: int | None = None,
    interval_date: tuple[str, str] | None = None,
    filter_str: str | None = None,
    limit: int | None = None,
    show_progress: bool = False,
):
    """
    Search scenes in a dataset with optional spatial, temporal, and metadata filters.

    If no output files are provided, entity IDs are printed to stdout.
    Otherwise, results are saved to the specified files. The output format is
    inferred from the file extension: .txt (entity IDs), .json (raw metadata),
    .gpkg/.geojson/.shp (vector), .html (interactive map).

    Parameters
    ----------
    dataset : str
        Dataset name (e.g. "aerial_combin").
    username : str, optional
        USGS ERS username. Defaults to USGS_USERNAME env var.
    token : str, optional
        USGS M2M API token. Defaults to USGS_TOKEN env var.
    output_files : list[str] or None
        Paths to output files. Supported extensions: .txt, .json, .gpkg, .geojson, .shp, .html.
    vector_file : str or None
        Path to a vector file used as spatial filter.
    location : tuple[float, float] or None
        (longitude, latitude) point filter.
    bbox : tuple[float, float, float, float] or None
        Bounding box filter as (xmin, ymin, xmax, ymax).
    clouds : int or None
        Maximum cloud cover percentage.
    interval_date : tuple[str, str] or None
        Date range filter as ("YYYY-MM-DD", "YYYY-MM-DD").
    filter_str : str or None
        Metadata filter string (e.g. "camera=H & resolution=6").
    limit : int or None
        Maximum number of scenes to return.
    show_progress : bool
        Whether to display a progress bar during search.
    """
    scene_filter = SceneFilter.from_args(
        location=location,
        bbox=bbox,
        max_cloud_cover=clouds,
        date_interval=interval_date,
        meta_filter=filter_str,
        g_file=vector_file,
    )

    try:
        with API(username, token) as api:
            if not output_files:
                for batch in api.batch_search(dataset, scene_filter, limit, "summary", show_progress):
                    for scene in batch:
                        print(scene["entityId"])
            else:
                # determine metadata type
                metadata_type = "summary" if len(output_files) == 1 and output_files[0].endswith(".txt") else "full"
                scenes = []
                for batch in api.batch_search(dataset, scene_filter, limit, metadata_type, show_progress):
                    scenes += batch

                for file in output_files:
                    directory = os.path.dirname(file)
                    if directory:
                        os.makedirs(directory, exist_ok=True)

                    if file.endswith(".txt"):
                        with open(file, "w", encoding="utf-8") as f:
                            f.write(f"#dataset={dataset}\n")
                            for scene in scenes:
                                f.write(scene["entityId"] + "\n")
                    elif file.endswith(".json"):
                        with open(file, "w", encoding="utf-8") as f:
                            json.dump(scenes, f, indent=4)
                    elif file.endswith((".gpkg", ".geojson", ".shp", ".html")):
                        gdf = utils.convert_response_to_gdf(scenes)
                        if file.endswith(".html"):
                            utils.save_in_html(gdf, file)
                        else:
                            utils.save_in_gfile(gdf, file)
    except USGSInvalidDataset:
        with API(username, token) as api:
            datasets = api.dataset_names()
        sorted_datasets = utils.sort_strings_by_similarity(dataset, datasets)[:50]
        choices = " | ".join(sorted_datasets)
        print(f"Invalid dataset : '{dataset}', it must be in :\n {choices}")
    except (FilterValueError, FilterFieldError) as e:
        print(e.__class__.__name__, " : ", e)


def download_scenes(
    textfile: str,
    username: str = None,
    token: str = None,
    dataset: str | None = None,
    product_number: int | None = None,
    output_dir: str = ".",
    max_workers: int = 5,
    overwrite: bool = False,
    show_progress: bool = True,
    extract: bool = True,
):
    """
    Download scenes listed in a text file produced by the search command.

    Parameters
    ----------
    textfile : str
        Path to the text file containing entity IDs (one per line, with optional
        ``#dataset=<name>`` header line).
    dataset : str or None
        Dataset name. If None, it is read from the ``#dataset=`` header in the text file.
    product_number : int or None
        Index of the product to download when multiple products are available.
        If None, the user is prompted to choose.
    output_dir : str
        Directory where downloaded files are saved.
    max_workers : int
        Number of parallel download threads.
    overwrite : bool
        Whether to overwrite already-downloaded files.
    show_progress : bool
        Whether to display a progress bar during download.
    extract : bool
        Whether to extract downloaded archives (.tar.gz, .gz) in place.
    """
    with API(username, token) as api:
        _, entity_ids = utils.read_textfile(textfile)
        with SceneDownloader(api) as dl:
            dl.download(
                dataset,
                entity_ids,
                output_dir=output_dir,
                product_number=product_number,
                overwrite=overwrite,
                max_workers=max_workers,
                show_progress=show_progress,
                extract=extract,
            )


def download_browse_images(
    source: str,
    output_dir: str,
    fmt: str = "tif",
    max_workers: int = 4,
    overwrite: bool = False,
    show_progress: bool = True,
) -> None:
    """
    Download browse (preview) images from a vector file or GeoDataFrame.

    Each scene is saved as an individual file named after its ``entity_id``.

    Parameters
    ----------
    source : str
        Path to the input vector file (any format supported by geopandas).
    output_dir : str
        Directory where downloaded images are saved.
    fmt : str, default "tif"
        Output format: ``"tif"`` (georeferenced GeoTIFF) or ``"jpg"``.
    max_workers : int, default 4
        Number of parallel download threads.
    overwrite : bool, default False
        If True, overwrite existing files.
    show_progress : bool, default True
        Whether to display a progress bar during download.
    """
    strategy = TifSaveStrategy() if fmt == "tif" else JpgSaveStrategy()
    downloader = BrowseDownloader(
        output_dir,
        strategy,
        overwrite=overwrite,
        max_workers=max_workers,
        show_progress=show_progress,
    )
    downloader.download(source)


def list_datasets(username: str = None, token: str = None, show_all: bool = False) -> list[str]:
    """
    Return the list of available dataset names from the USGS M2M API.

    Parameters
    ----------
    username : str, optional
        USGS ERS username. Defaults to USGS_USERNAME env var.
    token : str, optional
        USGS M2M API token. Defaults to USGS_TOKEN env var.
    show_all : bool
        If False (default), datasets whose name starts with ``"event"`` are excluded.

    Returns
    -------
    list[str]
        List of dataset names.
    """
    with API(username, token) as api:
        if show_all:
            datasets = api.dataset_names()
        else:
            datasets = [d for d in api.dataset_names() if not d.startswith("event")]
    return datasets


def list_dataset_filters(dataset: str, username: str = None, token: str = None) -> list[dict]:
    """
    Return the available metadata filters for a given dataset.

    Parameters
    ----------
    dataset : str
        Dataset name (e.g. "aerial_combin").
    username : str, optional
        USGS ERS username. Defaults to USGS_USERNAME env var.
    token : str, optional
        USGS M2M API token. Defaults to USGS_TOKEN env var.

    Returns
    -------
    list[dict]
        List of filter descriptors as returned by the USGS M2M API.
    """
    with API(username, token) as api:
        filters = api.dataset_filters(dataset)
    return filters
