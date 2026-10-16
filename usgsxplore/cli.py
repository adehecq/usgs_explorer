# pylint: disable=too-many-locals
# pylint: disable=unused-argument
"""
Description: Command line interface of the usgsxplore

Last modified: 2024
Author: Luc Godin
"""

from __future__ import annotations

import functools
import logging

import click
import geopandas as gpd
from tqdm.contrib.logging import logging_redirect_tqdm

from usgsxplore import utils
from usgsxplore.api import API
from usgsxplore.core import download_browse_images, search_scenes
from usgsxplore.errors import DownloadOptionsError
from usgsxplore.scene_downloader import SceneDownloader


# ----------------------------------------------------------------------------------------------------
# 									CALLBACK FUNCTIONS
# ----------------------------------------------------------------------------------------------------
def is_valid_output_format(ctx: click.Context, param: click.Parameter, value: tuple[str]) -> str:
    """
    Callback use to check the format of the output file of the search command.
    """
    formats = (".txt", ".json", ".gpkg", ".shp", ".geojson", ".html")
    for filename in value:
        if not filename.endswith(formats):
            choices = " | ".join(formats)
            raise click.BadParameter(f"'{value}' file format must be in {choices}")

    return value


def read_dataset_textfile(ctx: click.Context, param: click.Parameter, value: str | None):
    """
    This callback is use to fill the dataset parameter with either the first line of a textfile
    or with the dataset value in parameters
    """
    if value is not None:
        return value
    # treat the first line of the textfile given to see if the dataset is provided
    dataset = None
    with open(ctx.params.get("textfile"), encoding="utf-8") as file:
        first_line = file.readline().strip()
        if first_line.startswith("#"):
            spl = first_line.split("=", maxsplit=1)
            if len(spl) == 2 and "dataset" in spl[0]:
                dataset = spl[1].strip()

    if dataset is None:
        raise click.MissingParameter(ctx=ctx, param=ctx.params.get("dataset"))

    return dataset


def is_text_file(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    "callback for verify the validity of the textfile"
    if value is not None and not value.endswith(".txt"):
        raise click.BadParameter(f"'{value}' must be a textfile", ctx=ctx, param=param)
    return value


def is_vector_file(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    "callback for verify the validity of the vector file"
    if value is not None and not value.endswith((".shp", ".gpkg", ".geojson")):
        raise click.BadParameter(
            f"'{value}' must be a vector data file (.gpkg, .shp, .geojson)",
            ctx=ctx,
            param=param,
        )
    return value


def is_image_file(ctx: click.Context, param: click.Parameter, value: str) -> str:
    "callback for verify the validity of the output image file"
    if not value.lower().endswith((".png", ".jpg", ".jpeg")):
        raise click.BadParameter(f"'{value}' must be an image file (.png, .jpg)", ctx=ctx, param=param)
    return value


def is_html_file(ctx: click.Context, param: click.Parameter, value: str) -> str:
    "callback for verify the validity of the output html file"
    if not value.lower().endswith(".html"):
        raise click.BadParameter(f"'{value}' must be an html file", ctx=ctx, param=param)
    return value


# ----------------------------------------------------------------------------------------------------
# 									COMMAND LINE INTERFACE
# ----------------------------------------------------------------------------------------------------
@click.group()
@click.version_option(package_name="usgsxplore")
def cli() -> None:
    """
    Command line interface of the usgsxplore.
    Documentation : https://github.com/adehecq/usgs_explorer
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")


# ----------------------------------------------------------------------------------------------------
# 									SEARCH COMMAND
# ----------------------------------------------------------------------------------------------------
@click.command()
@click.argument("dataset", type=click.STRING)
@click.option(
    "-o",
    "--output",
    type=click.Path(file_okay=True),
    multiple=True,
    help="Output file : (txt, json, gpkg, shp, geojson, html [deprecated, use `viz map`])",
    callback=is_valid_output_format,
)
@click.option(
    "-vf",
    "--vector-file",
    type=click.Path(exists=True, file_okay=True),
    help="Vector file that will be used for spatial filter",
)
@click.option(
    "-l",
    "--location",
    type=click.FLOAT,
    nargs=2,
    help="Point of interest (longitude, latitude).",
)
@click.option(
    "-b",
    "--bbox",
    type=click.FLOAT,
    nargs=4,
    help="Bounding box (xmin, ymin, xmax, ymax).",
)
@click.option("-c", "--clouds", type=click.INT, help="Max. cloud cover (1-100).")
@click.option(
    "-i",
    "--interval-date",
    type=click.STRING,
    nargs=2,
    help="Date interval (start, end), (YYYY-MM-DD, YYYY-MM-DD).",
)
@click.option("-f", "--filter", type=click.STRING, help="String representation of metadata filter")
@click.option("-m", "--limit", type=click.INT, help="Max. results returned. Return all by default")
@click.option(
    "-e",
    "--entity-ids-file",
    type=click.Path(exists=True, file_okay=True),
    callback=is_text_file,
    help="Textfile of entity IDs to fetch metadata for, instead of searching (other filters are ignored).",
)
@click.option("--pbar", is_flag=True, default=False, help="Display a progress bar")
def search(
    dataset: str,
    output: str | None,
    vector_file: str | None,
    location: tuple[float, float] | None,
    bbox: tuple[float, float, float, float] | None,
    clouds: int | None,
    interval_date: tuple[str, str] | None,
    filter: str | None,  # pylint: disable=redefined-builtin
    limit: int | None,
    entity_ids_file: str | None,
    pbar: bool,
) -> None:
    """
    Search scenes in a dataset with filters.
    """
    search_scenes(
        dataset,
        output_files=list(output) or None,
        vector_file=vector_file,
        location=location or None,
        bbox=bbox or None,
        clouds=clouds,
        interval_date=interval_date or None,
        filter_str=filter,
        limit=limit,
        entity_ids_file=entity_ids_file,
        show_progress=pbar,
    )


# ----------------------------------------------------------------------------------------------------
# 									DOWNLOAD COMMAND
# ----------------------------------------------------------------------------------------------------
@click.command()
@click.argument("textfile", type=click.Path(exists=True, file_okay=True), callback=is_text_file)
@click.option(
    "--dataset",
    "-d",
    type=click.STRING,
    required=False,
    help="Dataset",
    callback=read_dataset_textfile,
)
@click.option(
    "--product-number",
    "-p",
    type=click.INT,
    required=False,
    help="The product index you want (default: None)",
    default=None,
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(dir_okay=True),
    default=".",
    help="Output directory",
)
@click.option(
    "--max-workers",
    "-m",
    type=click.INT,
    default=5,
    help="Max thread number (default: 5)",
)
@click.option("--overwrite", is_flag=True, default=False, help="Overwrite existing files")
@click.option("--hide-pbar", is_flag=True, default=False, help="Hide the progress bar")
@click.option("--no-extract", is_flag=True, default=False, help="Skip the extraction of files")
def download(
    textfile: str,
    dataset: str,
    product_number: int | None,
    output_dir: str,
    max_workers: int,
    overwrite: bool,
    hide_pbar: bool,
    no_extract: bool,
) -> None:
    """
    Download scenes with their entity ids provided in the textfile.
    The dataset can also be provide in the first line of the textfile : #dataset=declassii
    """
    _, entity_ids = utils.read_textfile(textfile)
    try:
        with logging_redirect_tqdm(), API() as api, SceneDownloader(api) as dl:
            dl.download(
                dataset,
                entity_ids,
                output_dir=output_dir,
                product_number=product_number,
                overwrite=overwrite,
                max_workers=max_workers,
                show_progress=not hide_pbar,
                extract=not no_extract,
            )
    except DownloadOptionsError as e:
        click.echo(
            f"{e!s}\nPlease specify the number of the product you want by using the option -p or --product-number."
        )


@click.command("download-browse")
@click.argument("vector-file", type=click.Path(exists=True, file_okay=True), callback=is_vector_file)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(dir_okay=True, resolve_path=True),
    default="./browse_images/",
    help="Output directory",
)
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(["tif", "jpg"], case_sensitive=False),
    default="tif",
    show_default=True,
    help="Output image format.",
)
@click.option(
    "--max-workers",
    "-m",
    type=click.INT,
    default=4,
    show_default=True,
    help="Number of parallel download threads.",
)
@click.option("--overwrite", is_flag=True, default=False, help="Overwrite existing files.")
@click.option("--hide-pbar", is_flag=True, default=False, help="Hide the progress bar.")
def download_browse(
    vector_file: str,
    output_dir: str,
    fmt: str,
    max_workers: int,
    overwrite: bool,
    hide_pbar: bool,
) -> None:
    """
    Download individual browse images from a vector file.

    Each scene is saved as a separate file (TIF or JPG) named after its entity_id.
    TIF files are georeferenced using corner coordinate columns from the vector file.
    """
    download_browse_images(
        vector_file,
        output_dir,
        fmt=fmt,
        max_workers=max_workers,
        overwrite=overwrite,
        show_progress=not hide_pbar,
    )


# ARGS and OPTIONS for every viz

vector_file_arg = click.argument("vector-file", type=click.Path(exists=True, file_okay=True), callback=is_vector_file)


def roi_options(func):
    """Add the ROI options to a viz command and merge them into a single `roi` argument."""

    @click.option(
        "--roi-vector-file",
        "-roi",
        type=click.Path(exists=True, file_okay=True),
        callback=is_vector_file,
        help="Region Of Interest (ROI) as a vector file, drawn in red on the figure.",
    )
    @click.option("--roi-location", type=click.FLOAT, nargs=2, help="ROI as a point (longitude, latitude).")
    @click.option("--roi-bbox", type=click.FLOAT, nargs=4, help="ROI as a bounding box (xmin, ymin, xmax, ymax).")
    @functools.wraps(func)
    def wrapper(*args, roi_vector_file, roi_location, roi_bbox, **kwargs):
        """Merge the ROI options into `roi` and call the wrapped command."""
        if sum(map(bool, (roi_vector_file, roi_location, roi_bbox))) > 1:
            raise click.UsageError("Use only one of --roi-vector-file, --roi-location and --roi-bbox.")
        return func(*args, roi=utils.roi_from_args(roi_vector_file, roi_location, roi_bbox), **kwargs)

    return wrapper


overwrite_option = click.option(
    "--overwrite", is_flag=True, default=False, help="Regenerate figures that already exist."
)

available_only_option = click.option(
    "--available-only", is_flag=True, default=False, help="Filter only available scenes"
)


def load_scenes(vector_file: str, available_only: bool) -> gpd.GeoDataFrame:
    """Load the scenes of a viz command, optionally keeping only the available ones."""
    gdf = utils.filter_only_available(vector_file) if available_only else utils.as_gdf(vector_file)
    if gdf.empty:
        raise click.UsageError("No scenes to visualize" + (" after --available-only" if available_only else ""))
    return gdf


@click.command("strip")
@vector_file_arg
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(dir_okay=True, resolve_path=True),
    default="./strip_viz/",
    show_default=True,
    help="Output directory for the strip figures.",
)
@roi_options
@click.option(
    "--max-workers",
    "-m",
    type=click.INT,
    default=4,
    show_default=True,
    help="Number of strips rendered in parallel (one process each).",
)
@overwrite_option
@available_only_option
@click.option(
    "--work-dir",
    type=click.Path(dir_okay=True, resolve_path=True),
    help="Directory where browse images are downloaded. [default: OUTPUT_DIR/browse_images]",
)
@click.option(
    "--clean/--no-clean",
    default=True,
    show_default=True,
    help="Delete downloaded browse images once figures are saved.",
)
def strip_viz(
    vector_file: str,
    output_dir: str,
    roi: utils.RoiType | None,
    max_workers: int,
    overwrite: bool,
    available_only: bool,
    work_dir: str | None,
    clean: bool,
) -> None:
    """
    Generate one preview figure per strip from a vector file.

    Scenes are grouped into strips by entity_id. For each strip, browse images are
    downloaded and mosaicked, and a JPG figure named after the strip id is saved with
    a mosaic view next to a context map (centered on the ROI if provided).
    """
    from usgsxplore.viz.strip_figures import generate_strip_figures

    generate_strip_figures(
        load_scenes(vector_file, available_only),
        output_dir,
        roi,
        max_workers=max_workers,
        overwrite=overwrite,
        work_dir=work_dir,
        clean_work_dir=clean,
    )


@click.command("footprint")
@vector_file_arg
@click.option(
    "--output-file",
    "-o",
    type=click.Path(file_okay=True),
    default="scenes_footprint.png",
    show_default=True,
    callback=is_image_file,
    help="Output file for the visualization.",
)
@roi_options
@overwrite_option
@available_only_option
def footprint_viz(
    vector_file: str,
    output_file: str,
    roi: utils.RoiType | None,
    overwrite: bool,
    available_only: bool,
) -> None:
    """Plot the scene footprints over a satellite basemap, as a PNG or JPG."""
    from usgsxplore.viz.scenes_footprint import generate_scenes_footprint

    generate_scenes_footprint(load_scenes(vector_file, available_only), output_file, roi, overwrite)


@click.command("density")
@vector_file_arg
@click.option(
    "--output-file",
    "-o",
    type=click.Path(file_okay=True),
    default="scenes_density.png",
    show_default=True,
    callback=is_image_file,
    help="Output file for the visualization.",
)
@roi_options
@overwrite_option
@available_only_option
def density_viz(
    vector_file: str,
    output_file: str,
    roi: utils.RoiType | None,
    overwrite: bool,
    available_only: bool,
) -> None:
    """Plot the scene overlap density over a satellite basemap, as a PNG or JPG."""
    from usgsxplore.viz.scenes_density import generate_scenes_density

    generate_scenes_density(load_scenes(vector_file, available_only), output_file, roi, overwrite=overwrite)


@click.command("map")
@vector_file_arg
@click.option(
    "--output-file",
    "-o",
    type=click.Path(file_okay=True),
    default="scenes_map.html",
    show_default=True,
    callback=is_html_file,
    help="Output file for the visualization.",
)
@roi_options
@overwrite_option
@available_only_option
def map_viz(
    vector_file: str,
    output_file: str,
    roi: utils.RoiType | None,
    overwrite: bool,
    available_only: bool,
) -> None:
    """Save the scene footprints as an interactive HTML map, with browse images in popups."""
    from usgsxplore.viz.html_map import generate_html_map

    generate_html_map(load_scenes(vector_file, available_only), output_file, roi, overwrite=overwrite)


@click.group()
def viz() -> None:
    """Create some visualization"""


@click.group()
def info() -> None:
    """
    Display some information.
    """


@click.command()
@click.option("-a", "--all", is_flag=True, help="display also all event dataset")
def dataset(all: bool) -> None:
    """
    Display the list of available dataset in the API.
    """
    api = API()
    if all:
        click.echo(api.dataset_names())
    else:
        dataset_list = [dataset for dataset in api.dataset_names() if not dataset.startswith("event")]
        click.echo(dataset_list)
    api.logout()


@click.command()
@click.argument("dataset", type=click.STRING)
def filters(dataset: str) -> None:
    """
    Display a list of available filter field for a dataset.
    """
    api = API()
    dataset_filters = api.dataset_filters(dataset)
    table = [["field id", "field lbl", "field sql"]]
    for filt in dataset_filters:
        table.append(
            [
                filt["id"],
                filt["fieldLabel"],
                filt["searchSql"].split(" ", maxsplit=1)[0],
            ]
        )
    click.echo(utils.format_table(table))

    api.logout()


cli.add_command(search)
cli.add_command(download)
cli.add_command(download_browse)
cli.add_command(info)
cli.add_command(viz)
info.add_command(dataset)
info.add_command(filters)
viz.add_command(strip_viz)
viz.add_command(footprint_viz)
viz.add_command(density_viz)
viz.add_command(map_viz)


if __name__ == "__main__":
    cli()
