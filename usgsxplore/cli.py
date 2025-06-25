# pylint: disable=too-many-locals
# pylint: disable=unused-argument
"""
Description: Command line interface of the usgsxplore

Last modified: 2024
Author: Luc Godin
"""

import json
import os

import click
import geopandas as gpd

import usgsxplore.utils as utils
from usgsxplore.api import API
from usgsxplore.errors import (
    DownloadOptionsError,
    FilterFieldError,
    FilterValueError,
    USGSInvalidDataset,
)
from usgsxplore.filter import SceneFilter


# ----------------------------------------------------------------------------------------------------
# 									CALLBACK FUNCTIONS
# ----------------------------------------------------------------------------------------------------
def is_valid_output_format(
    ctx: click.Context, param: click.Parameter, value: tuple[str]
) -> str:
    """
    Callback use to check the format of the output file of the search command.
    """
    formats = (".txt", ".json", ".gpkg", ".shp", ".geojson", ".html")
    for filename in value:
        if not filename.endswith(formats):
            choices = " | ".join(formats)
            raise click.BadParameter(f"'{value}' file format must be in {choices}")

    return value


def read_dataset_textfile(
    ctx: click.Context, param: click.Parameter, value: str | None
):
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


def is_text_file(ctx: click.Context, param: click.Parameter, value: str) -> str:
    "callback for verify the validity of the textfile"
    if not value.endswith(".txt"):
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
def cli() -> None:
    """
    Command line interface of the usgsxplore.
    Documentation : https://github.com/adehecq/usgs_explorer
    """


# ----------------------------------------------------------------------------------------------------
# 									SEARCH COMMAND
# ----------------------------------------------------------------------------------------------------
@click.command()
@click.option(
    "-u",
    "--username",
    type=click.STRING,
    required=True,
    help="EarthExplorer username.",
    envvar="USGS_USERNAME",
)
@click.option(
    "-t",
    "--token",
    type=click.STRING,
    help="EarthExplorer token.",
    required=True,
    envvar="USGS_TOKEN",
)
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
@click.option(
    "-f", "--filter", type=click.STRING, help="String representation of metadata filter"
)
@click.option(
    "-m", "--limit", type=click.INT, help="Max. results returned. Return all by default"
)
@click.option("--pbar", is_flag=True, default=False, help="Display a progress bar")
def search(
    username: str,
    token: str,
    dataset: str,
    output: str | None,
    vector_file: str | None,
    location: tuple[float, float] | None,
    bbox: tuple[float, float, float, float] | None,
    clouds: int | None,
    interval_date: tuple[str, str] | None,
    filter: str | None,  # pylint: disable=redefined-builtin
    limit: int | None,
    pbar: bool,
) -> None:
    """
    Search scenes in a dataset with filters.
    """
    api = API(username, token)
    scene_filter = SceneFilter.from_args(
        location=location,
        bbox=bbox,
        max_cloud_cover=clouds,
        date_interval=interval_date,
        meta_filter=filter,
        g_file=vector_file,
    )

    try:
        if not output:
            for batch_scenes in api.batch_search(
                dataset, scene_filter, limit, "summary", pbar
            ):
                for scene in batch_scenes:
                    click.echo(scene["entityId"])

        else:
            # we adapt the metadata type only if their are one textfile
            metadata_type = (
                "summary" if len(output) == 1 and output[0].endswith(".txt") else "full"
            )
            scenes = []

            for batch_scenes in api.batch_search(
                dataset, scene_filter, limit, metadata_type, pbar
            ):
                scenes += batch_scenes

            for file in output:
                # create directories
                directory = os.path.dirname(file)
                if directory:
                    os.makedirs(directory, exist_ok=True)

                if file.endswith(".txt"):
                    with open(file, "w", encoding="utf-8") as file:
                        file.write(f"#dataset={dataset}\n")
                        for scene in scenes:
                            file.write(scene["entityId"] + "\n")

                elif file.endswith(".json"):
                    with open(file, "w", encoding="utf-8") as f:
                        json.dump(scenes, f, indent=4)

                elif file.endswith((".gpkg", ".geojson", ".shp", ".html")):
                    gdf = utils.to_gdf(scenes)
                    if file.endswith(".html"):
                        utils.save_in_html(gdf, file)
                    else:
                        utils.save_in_gfile(gdf, file)

    # if dataset is invalid print a list of similar dataset for the user
    except USGSInvalidDataset:
        datasets = api.dataset_names()
        sorted_datasets = utils.sort_strings_by_similarity(dataset, datasets)[:50]
        choices = " | ".join(sorted_datasets)
        click.echo(f"Invalid dataset : '{dataset}', it must be in :\n {choices}")
    # print only the message when a filter error is raise
    except (FilterValueError, FilterFieldError) as e:
        print(e.__class__.__name__, " : ", e)

    api.logout()


# ----------------------------------------------------------------------------------------------------
# 									DOWNLOAD COMMAND
# ----------------------------------------------------------------------------------------------------
@click.command()
@click.option(
    "-u",
    "--username",
    type=click.STRING,
    help="EarthExplorer username.",
    envvar="USGS_USERNAME",
)
@click.option(
    "-t",
    "--token",
    type=click.STRING,
    help="EarthExplorer token.",
    required=True,
    envvar="USGS_TOKEN",
)
@click.argument(
    "textfile", type=click.Path(exists=True, file_okay=True), callback=is_text_file
)
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
@click.option(
    "--overwrite", is_flag=True, default=False, help="Overwrite existing files"
)
@click.option("--hide-pbar", is_flag=True, default=False, help="Hide the progress bar")
@click.option(
    "--no-extract", is_flag=True, default=False, help="Skip the extraction of files"
)
def download(
    username: str,
    token: str,
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
    api = API(username, token)
    entity_ids = utils.read_textfile(textfile)
    try:
        api.download(
            dataset,
            entity_ids,
            product_number,
            output_dir,
            overwrite,
            max_workers,
            show_progress=not hide_pbar,
            extract=not no_extract,
        )
    except DownloadOptionsError as e:
        click.echo(
            f"{str(e)}\nPlease specify the number of the product you want by using the option -p or --product-number."
        )
    api.logout()


@click.command("download-browse")
@click.argument(
    "vector-file", type=click.Path(exists=True, file_okay=True), callback=is_vector_file
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(dir_okay=True, resolve_path=True),
    default="./browse_images/",
    help="Output directory",
)
@click.option("--pbar", is_flag=True, default=True, help="Display a progress bar.")
def download_browse(vector_file: str, output_dir: str, pbar: bool) -> None:
    """
    Download browse images of a vector data file locally.
    """
    # create the directory if it not exist
    os.makedirs(output_dir, exist_ok=True)

    # read the vector file
    gdf = gpd.read_file(vector_file)
    print(gdf.shape)

    # get the list of browse_url
    url_list = gdf["browse_url"].tolist()

    # download the list of url with download_browse_img
    _ = utils.download_browse_img(url_list, output_dir, pbar)

    # update the vector file with browse_path added
    gdf = utils.update_gdf_browse(gdf, output_dir)
    utils.save_in_gfile(gdf, vector_file)


@click.group()
def info() -> None:
    """
    Display some information.
    """


@click.command()
@click.option(
    "-u",
    "--username",
    type=click.STRING,
    help="EarthExplorer username.",
    envvar="USGS_USERNAME",
)
@click.option(
    "-t",
    "--token",
    type=click.STRING,
    help="EarthExplorer token.",
    required=True,
    envvar="USGS_TOKEN",
)
@click.option("-a", "--all", is_flag=True, help="display also all event dataset")
def dataset(username: str, token: str, all: bool) -> None:
    """
    Display the list of available dataset in the API.
    """
    api = API(username, token)
    if all:
        click.echo(api.dataset_names())
    else:
        dataset_list = [
            dataset
            for dataset in api.dataset_names()
            if not dataset.startswith("event")
        ]
        click.echo(dataset_list)
    api.logout()


@click.command()
@click.option(
    "-u",
    "--username",
    type=click.STRING,
    help="EarthExplorer username.",
    envvar="USGS_USERNAME",
)
@click.option(
    "-t",
    "--token",
    type=click.STRING,
    help="EarthExplorer token.",
    required=True,
    envvar="USGS_TOKEN",
)
@click.argument("dataset", type=click.STRING)
def filters(username: str, token: str, dataset: str) -> None:
    """
    Display a list of available filter field for a dataset.
    """
    api = API(username, token)
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
