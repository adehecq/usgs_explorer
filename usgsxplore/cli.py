# pylint: disable=too-many-locals
"""
Description: Command line interface of the usgsxplore

Last modified: 2024
Author: Luc Godin
"""
import json

import click

from usgsxplore.api import API
from usgsxplore.filter import SceneFilter
from usgsxplore.utils import read_textfile, to_gpkg


# ----------------------------------------------------------------------------------------------------
# 									CALLBACK FUNCTIONS
# ----------------------------------------------------------------------------------------------------
def is_valid_output_format(ctx: click.Context, param: click.Parameter, value: str) -> str:
    formats = (".txt", ".json", ".gpkg", ".shp", ".geojson")
    if not value.endswith(formats):
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


def is_text_file(ctx: click.Context, param: click.Parameter, value: str) -> str:
    "callback for verify the validity of the textfile"
    if not value.endswith(".txt"):
        raise click.BadParameter(f"'{value}' must be a textfile", ctx=ctx, param=param)
    return value


# ----------------------------------------------------------------------------------------------------
# 									COMMAND LINE INTERFACE
# ----------------------------------------------------------------------------------------------------
@click.group()
def cli() -> None:
    """
    Command line interface of the usgsxplore
    """


# ----------------------------------------------------------------------------------------------------
# 									SEARCH COMMAND
# ----------------------------------------------------------------------------------------------------
@click.command()
@click.option("-u", "--username", type=click.STRING, help="EarthExplorer username.", envvar="USGSXPLORE_USERNAME")
@click.option(
    "-p", "--password", type=click.STRING, help="EarthExplorer password.", required=False, envvar="USGSXPLORE_PASSWORD"
)
@click.option(
    "-t", "--token", type=click.STRING, help="EarthExplorer token.", required=False, envvar="USGSXPLORE_TOKEN"
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
    Use the API class to search scenes in a dataset, and save the result in multiple format.
    If output is None just print entity ids of scenes, else save the result in the output file.
    All thoses format are accepted:
    - textfile (.txt) : save all entity ids into the textfile
    - json (.json) : save all scenes metadata into the json file
    - geopackage (.gpkg) : save all scenes metadata into the geopackage file using EPSG:4326
    - shapefile (.shp) : save all scenes metadata into the shapefile file using EPSG:4326
    - geojson (.geojson) : save all scenes metadata into the geojson file using EPSG:4326

    :param username: USGS username can be take in env at "USGSXPLORE_USERNAME"
    :param password: USGS password can be take in env at "USGSXPLORE_PASSWORD"
    :param token: USGS token can be take in env at "USGSXPLORE_TOKEN"
    :param dataset: dataset name for the search
    :param output: Output file : (txt, json, gpkg, shp, geojson)
    :param location: Point of interest (longitude, latitude).
    :param bbox: Bounding box (xmin, ymin, xmax, ymax).
    :param clouds: Max. cloud cover (1-100).
    :param interval_date: Date interval (start, end), (YYYY-MM-DD, YYYY-MM-DD).
    :param filter: String representation of metadata filter
    :param limit: Max. results returned. Return all by default
    :param pbar: Display a progress bar
    """
    api = API(username, password=password, token=token)
    scene_filter = SceneFilter.from_args(
        location=location, bbox=bbox, max_cloud_cover=clouds, date_interval=interval_date, meta_filter=filter
    )
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
            to_gpkg(scenes, output)

    api.logout()


# ----------------------------------------------------------------------------------------------------
# 									DOWNLOAD COMMAND
# ----------------------------------------------------------------------------------------------------
@click.command()
@click.option("-u", "--username", type=click.STRING, help="EarthExplorer username.", envvar="USGSXPLORE_USERNAME")
@click.option(
    "-p", "--password", type=click.STRING, help="EarthExplorer password.", required=False, envvar="USGSXPLORE_PASSWORD"
)
@click.option(
    "-t", "--token", type=click.STRING, help="EarthExplorer token.", required=False, envvar="USGSXPLORE_TOKEN"
)
@click.argument("textfile", type=click.Path(exists=True, file_okay=True), callback=is_text_file)
@click.option("--dataset", "-d", type=click.STRING, required=False, help="Dataset", callback=read_dataset_textfile)
@click.option("--output-dir", "-o", type=click.Path(dir_okay=True), default=".", help="Output directory")
@click.option("--pbar", "-b", type=click.IntRange(0, 2), default=2, help="Type of progression displaying (0,1,2)")
@click.option("--max-thread", "-m", type=click.INT, default=5)
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
    Download scenes with their entity ids provided in the textfile. The dataset must be provided.

    :param username: USGS username can be take in env at "USGSXPLORE_USERNAME"
    :param password: USGS password can be take in env at "USGSXPLORE_PASSWORD"
    :param token: USGS token can be take in env at "USGSXPLORE_TOKEN"
    :param textfile: path of the text file containing entity ids
    :param dataset: dataset name of scenes
    :param output_dir: path of the output directory
    :param pbar: Type of progression displaying (0,1,2)
    :param max_thread: maximum number of thread for the downloading
    :param overwrite: Overwrite existing files
    """
    api = API(username, password=password, token=token)
    entity_ids = read_textfile(textfile)
    api.download(dataset, entity_ids, output_dir, max_thread, overwrite, pbar)
    api.logout()


cli.add_command(search)
cli.add_command(download)

if __name__ == "__main__":
    cli()
