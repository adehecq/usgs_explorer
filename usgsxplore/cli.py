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

from usgsxplore.api import API
from usgsxplore.errors import FilterFieldError, FilterValueError, USGSInvalidDataset
from usgsxplore.filter import SceneFilter
from usgsxplore.utils import (
    download_browse_img,
    read_textfile,
    save_in_gfile,
    sort_strings_by_similarity,
    to_gdf,
    update_gdf_browse,
)


# ----------------------------------------------------------------------------------------------------
# 									CALLBACK FUNCTIONS
# ----------------------------------------------------------------------------------------------------
def is_valid_output_format(ctx: click.Context, param: click.Parameter, value: str) -> str:
    """
    Callback use to check the format of the output file of the search command.
    """
    if value is None:
        return None
    formats = (".txt", ".json", ".gpkg", ".shp", ".geojson")
    if not value.endswith(formats):
        choices = " | ".join(formats)
        raise click.BadParameter(f"'{value}' file format must be in {choices}")
    return value


def check_log(ctx: click.Context, param: click.Parameter, value: str | None) -> str:
    if value is not None:
        return value
    if ctx.params.get("password") is None:
        raise click.ClickException("Missing argument -p, --password or -t, --token")


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


def is_text_file(ctx: click.Context, param: click.Parameter, value: str) -> str:
    "callback for verify the validity of the textfile"
    if not value.endswith(".txt"):
        raise click.BadParameter(f"'{value}' must be a textfile", ctx=ctx, param=param)
    return value


def is_vector_file(ctx: click.Context, param: click.Parameter, value: str) -> str:
    "callback for verify the validity of the vector file"
    if not value.endswith((".shp", ".gpkg", ".geojson")):
        raise click.BadParameter(f"'{value}' must be a vector data file (.gpkg, .shp, .geojson)", ctx=ctx, param=param)
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
    "-u", "--username", type=click.STRING, required=True, help="EarthExplorer username.", envvar="USGS_USERNAME"
)
@click.option(
    "-p", "--password", type=click.STRING, help="EarthExplorer password.", required=False, envvar="USGS_PASSWORD"
)
@click.option(
    "-t",
    "--token",
    type=click.STRING,
    help="EarthExplorer token.",
    required=False,
    envvar="USGS_TOKEN",
    callback=check_log,
)
@click.argument("dataset", type=click.STRING)
@click.option(
    "-o",
    "--output",
    type=click.Path(file_okay=True),
    help="Output file : (txt, json, gpkg, shp, geojson)",
    callback=is_valid_output_format,
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
@click.option("--pbar", is_flag=True, default=False, help="Display a progress bar")
def search(
    username: str,
    password: str | None,
    token: str | None,
    dataset: str,
    output: str | None,
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
    api = API(username, password=password, token=token)
    scene_filter = SceneFilter.from_args(
        location=location, bbox=bbox, max_cloud_cover=clouds, date_interval=interval_date, meta_filter=filter
    )

    try:
        if output is None:
            for batch_scenes in api.batch_search(dataset, scene_filter, limit, None, pbar):
                for scene in batch_scenes:
                    click.echo(scene["entityId"])

        else:
            if output.endswith(".txt"):
                with open(output, "w", encoding="utf-8") as file:
                    file.write(f"#dataset={dataset}\n")
                    for batch_scenes in api.batch_search(dataset, scene_filter, limit, None, pbar):
                        for scene in batch_scenes:
                            file.write(scene["entityId"] + "\n")
            elif output.endswith(".json"):
                with open(output, "w", encoding="utf-8") as file:
                    scenes = []
                    for batch_scenes in api.batch_search(dataset, scene_filter, limit, None, pbar):
                        scenes += batch_scenes
                    json.dump(scenes, file, indent=4)
            elif output.endswith((".gpkg", ".geojson", "shp")):
                scenes = []
                for batch_scenes in api.batch_search(dataset, scene_filter, limit, "full", pbar):
                    scenes += batch_scenes
                gdf = to_gdf(scenes)
                save_in_gfile(gdf, output)

    # if dataset is invalid print a list of similar dataset for the user
    except USGSInvalidDataset:
        datasets = api.dataset_names()
        sorted_datasets = sort_strings_by_similarity(dataset, datasets)[:50]
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
@click.option("-u", "--username", type=click.STRING, help="EarthExplorer username.", envvar="USGS_USERNAME")
@click.option(
    "-p", "--password", type=click.STRING, help="EarthExplorer password.", required=False, envvar="USGS_PASSWORD"
)
@click.option("-t", "--token", type=click.STRING, help="EarthExplorer token.", required=False, envvar="USGS_TOKEN")
@click.argument("textfile", type=click.Path(exists=True, file_okay=True), callback=is_text_file)
@click.option("--dataset", "-d", type=click.STRING, required=False, help="Dataset", callback=read_dataset_textfile)
@click.option("--output-dir", "-o", type=click.Path(dir_okay=True), default=".", help="Output directory")
@click.option("--pbar", "-b", type=click.IntRange(0, 2), default=2, help="Type of progression displaying (0,1,2)")
@click.option("--max-thread", "-m", type=click.INT, default=5, help="Max thread number (default: 5)")
@click.option("--overwrite", is_flag=True, default=False, help="Overwrite existing files")
def download(
    username: str,
    password: str | None,
    token: str | None,
    textfile: str,
    dataset: str,
    output_dir: str,
    pbar: int,
    max_thread: int,
    overwrite: bool,
) -> None:
    """
    Download scenes with their entity ids provided in the textfile.
    The dataset can also be provide in the first line of the textfile : #dataset=declassii
    """
    api = API(username, password=password, token=token)
    entity_ids = read_textfile(textfile)
    api.download(dataset, entity_ids, output_dir, max_thread, overwrite, pbar)
    api.logout()


@click.command("download-browse")
@click.argument("vector-file", type=click.Path(exists=True, file_okay=True), callback=is_vector_file)
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
    Download browse images of a vector data file localy.
    """
    # create the directory if it not exist
    os.makedirs(output_dir, exist_ok=True)

    # read the vector file
    gdf = gpd.read_file(vector_file)
    print(gdf.shape)

    # get the list of browse_url
    url_list = gdf["browse_url"].tolist()

    # download the list of url with download_browse_img
    dl_recap = download_browse_img(url_list, output_dir, pbar)

    # update the vector file with browse_path added
    gdf = update_gdf_browse(gdf, dl_recap, output_dir)
    save_in_gfile(gdf, vector_file)


@click.group()
def info() -> None:
    """
    Display some informations.
    """


@click.command()
@click.option("-u", "--username", type=click.STRING, help="EarthExplorer username.", envvar="USGS_USERNAME")
@click.option(
    "-p", "--password", type=click.STRING, help="EarthExplorer password.", required=False, envvar="USGS_PASSWORD"
)
@click.option("-t", "--token", type=click.STRING, help="EarthExplorer token.", required=False, envvar="USGS_TOKEN")
@click.option("-a", "--all", is_flag=True, help="display also all event dataset")
def dataset(username: str, password: str | None, token: str | None, all: bool) -> None:
    """
    Display the list of available dataset in the API.
    """
    api = API(username, password, token)
    if all:
        click.echo(api.dataset_names())
    else:
        dataset_list = [dataset for dataset in api.dataset_names() if not dataset.startswith("event")]
        click.echo(dataset_list)
    api.logout()


@click.command("filter-field")
def filter_field() -> None:
    """
    Display a list of available filter field for a dataset.
    """


@click.command("filter-value")
def filter_value() -> None:
    """
    Display a list of available filter values for a dataset.
    """


cli.add_command(search)
cli.add_command(download)
cli.add_command(download_browse)
cli.add_command(info)
info.add_command(dataset)
info.add_command(filter_field)
info.add_command(filter_value)


if __name__ == "__main__":
    cli()
