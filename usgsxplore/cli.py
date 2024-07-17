"""
Description: module the cli of the usgsxplore

Last modified: 2024
Author: Luc Godin
"""
import json
import os
import sys

import click

from usgsxplore.api import API
from usgsxplore.filter import SceneFilter
from usgsxplore.utils import to_gpkg


@click.group()
def cli() -> None:
    """
    Command line interface of the usgsxplore
    """
    pass


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
@click.option("-m", "--limit", type=click.INT, help="Max. results returned.")
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
    filter: str | None,
    limit: int | None,
) -> None:
    api = API(username, password=password, token=token)
    scene_filter = SceneFilter.from_args(
        location=location, bbox=bbox, max_cloud_cover=clouds, date_interval=interval_date, meta_filter=filter
    )
    if output is None:
        for batch_scenes in api.batch_search(dataset, scene_filter, limit, None):
            for scene in batch_scenes:
                click.echo(scene["entityId"])

    else:
        if output.endswith(".txt"):
            with open(output, "w", encoding="utf-8") as file:
                for batch_scenes in api.batch_search(dataset, scene_filter, limit, None):
                    for scene in batch_scenes:
                        file.write(scene["entityId"] + "\n")
        elif output.endswith(".json"):
            with open(output, "w", encoding="utf-8") as file:
                scenes = []
                for batch_scenes in api.batch_search(dataset, scene_filter, limit, None):
                    scenes += batch_scenes
                json.dump(scenes, file, indent=4)
        elif output.endswith((".gpkg", ".geojson", "shp")):
            click.echo("hey")
            # scenes = []
            # for batch_scenes in api.batch_search(dataset, scene_filter, limit, "full"):
            #     scenes += batch_scenes

            # to_gpkg(scenes, output)

    api.logout()


cli.add_command(search)

if __name__ == "__main__":
    cli()
