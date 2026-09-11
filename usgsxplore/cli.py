# pylint: disable=too-many-locals
# pylint: disable=unused-argument
"""
Description: Command line interface of the usgsxplore

Last modified: 2024
Author: Luc Godin
"""

from __future__ import annotations

import click

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


def is_vector_file(ctx: click.Context, param: click.Parameter, value: str) -> str:
    "callback for verify the validity of the vector file"
    if not value.endswith((".shp", ".gpkg", ".geojson")):
        raise click.BadParameter(
            f"'{value}' must be a vector data file (.gpkg, .shp, .geojson)",
            ctx=ctx,
            param=param,
        )
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
    help="Output file : (txt, json, html, gpkg, shp, geojson)",
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
        with API() as api, SceneDownloader(api) as dl:
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
    for _i, filt in enumerate(dataset_filters):
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
info.add_command(dataset)
info.add_command(filters)


if __name__ == "__main__":
    cli()
