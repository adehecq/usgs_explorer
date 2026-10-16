"""
Description: module contain some utils functions and class

Last modified: 2024
Author: Luc Godin
"""

from __future__ import annotations

import re
import warnings
from difflib import SequenceMatcher
from pathlib import Path
import logging

import geopandas as gpd
import pandas as pd
from shapely import MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry

logger = logging.getLogger(__name__)


def convert_response_to_gdf(scenes_metadata: list[dict]) -> gpd.GeoDataFrame:
    """
    This method convert the file scenes.jsonl into a geodataframe with the spatialCoverage for the geometry

    :param scenes_metadata: result of the search
    :return: GeoDataFrame to generate a geopackage
    """
    geometries = []
    attributes = {}

    # loop in every line of the scenes file
    for scene in scenes_metadata:
        geom_type = scene["spatialCoverage"]["type"]
        if geom_type == "Polygon":
            geometries.append(Polygon(scene["spatialCoverage"]["coordinates"][0]))
        elif geom_type == "MultiPolygon":
            geometries.append(MultiPolygon(scene["spatialCoverage"]["coordinates"]))
        elif geom_type == "Point":
            geometries.append(Point(scene["spatialCoverage"]["coordinates"]))
        else:
            continue

        # add all metadata attribute
        for field in scene.get("metadata"):
            field_name = _to_snake_case(field.get("fieldName"))
            attributes.setdefault(field_name, []).append(field.get("value"))

        if len(scene["browse"]) > 0:
            attributes.setdefault("browse_url", []).append(scene["browse"][0]["browsePath"])
        else:
            attributes.setdefault("browse_url", []).append(None)

    # create geodataframe with attributes and geometries
    return gpd.GeoDataFrame(data=attributes, geometry=geometries, crs="EPSG:4326")


RoiType = str | Path | gpd.GeoDataFrame | BaseGeometry


def as_gdf(source: RoiType) -> gpd.GeoDataFrame:
    """Load a GeoDataFrame from a file path or a lon/lat geometry, or pass one through unchanged."""
    match source:
        case gpd.GeoDataFrame():
            return source
        case BaseGeometry():
            return gpd.GeoDataFrame(geometry=[source], crs="EPSG:4326")
        case _:
            return gpd.read_file(source)


def roi_from_args(
    vector_file: str | Path | None = None,
    location: tuple[float, float] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> RoiType | None:
    """Combine the spatial inputs into a single ROI, with the same precedence as `SceneFilter.from_args`."""
    if vector_file:
        return vector_file
    if location:
        return Point(*location)
    if bbox:
        return box(*bbox)
    return None


AVAILABLE_COLNAMES = {"download_available", "down_load_available", "high_resolution_download_avail"}


def available_column(source: str | Path | gpd.GeoDataFrame) -> pd.Series:
    """Return the download availability of each scene as a bool Series, all True if no availability column exists."""
    gdf = as_gdf(source)

    column = next((gdf[col] for col in AVAILABLE_COLNAMES if col in gdf.columns), None)

    if column is None:
        logger.warning("No download availability column found among: %s", ", ".join(gdf.columns))
        return pd.Series(True, index=gdf.index)

    # Formats without a native bool type may read the flag back as 0/1
    return column.astype(bool)


def filter_only_available(source: str | Path | gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = as_gdf(source)
    return gdf[available_column(gdf)]


def save_in_gfile(gdf: gpd.GeoDataFrame, vector_file: str = "scenes.gpkg") -> None:
    """
    This function save the geodataframe into the vector_file given

    :param gdf: geodataframe that will be saved
    :param vector_file: output vector file
    """
    # save the geodataframe in a geospatial file
    if vector_file.endswith(".shp"):
        # here we ignore warnings that tell us all field are truncated
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=r"Normalized/laundered field name: '.+' to '.+'")
            gdf.to_file(vector_file)
    elif vector_file.endswith(".gpkg"):
        gdf.to_file(vector_file, driver="GPKG")
    elif vector_file.endswith(".geojson"):
        gdf.to_file(vector_file, driver="GeoJSON")
    else:
        raise ValueError(f"The file '{vector_file}' need to end with : .shp|.gpkg|.geojson")


def read_textfile(textfile: str) -> tuple[str | None, list[str]]:
    """
    This function read a textfile and return a list of ids found in the textfile,
    without comment line

    :param textfile: path of the textfile
    """
    list_ids = []
    dataset = None

    with open(textfile, encoding="utf-8") as file:
        lines = file.readlines()

    if lines and lines[0].strip().startswith("#"):
        spl = lines[0].strip().split("=", maxsplit=1)
        if len(spl) == 2 and "dataset" in spl[0]:
            dataset = spl[1].strip()
        lines = lines[1:]

    # loop in other line and don't take the comment
    for line in lines:
        if not line.strip().startswith("#"):
            spl = line.split("#", maxsplit=1)
            entity_id = spl[0].strip()
            if entity_id:
                list_ids.append(entity_id)
    return (dataset, list_ids)


def sort_strings_by_similarity(ref_str: str, list_str: list[str]) -> list[str]:
    """
    This function return the list_str given sorted in terms of string similarity with the ref_str.

    :param ref_str: reference string for sort the list
    :param list_str: list of string to be sorted
    """
    # Calculate similarity score for each string in list_str with ref_str
    similarity_scores = [SequenceMatcher(None, ref_str, str_).ratio() for str_ in list_str]

    # Sort list_str based on similarity scores
    sorted_list_str = [str_ for _, str_ in sorted(zip(similarity_scores, list_str), reverse=True)]

    return sorted_list_str


def format_table(data: list[list]) -> str:
    """
    Return a string representation of a 2 dimensional table

    :param data: 2 dimensional table
    :return: string representation
    """
    table_str = ""
    col_widths = [max(len(str(item)) for item in col) for col in zip(*data)]

    # consider the first line like a header
    header = "   ".join(f"{item!s:<{col_widths[i]}}" for i, item in enumerate(data[0])) + "\n"
    table_str += header

    # construct other line
    for row in data[1:]:
        table_str += " | ".join(f"{item!s:<{col_widths[i]}}" for i, item in enumerate(row)) + "\n"

    return table_str


def _to_snake_case(string: str) -> str:
    """
    Convert a string to snake_case.

    Examples:
        "Entity ID" -> "entity_id"
        "MyVariableName" -> "my_variable_name"
        "  Leading and trailing  " -> "leading_and_trailing"

    Args:
        string (str): Input string.

    Returns:
        str: Snake_case version of the string.
    """
    # 1. Strip leading/trailing whitespace
    string = string.strip()

    # 2. Replace spaces, hyphens, and dots with underscores
    string = re.sub(r"[\s\-\.]+", "_", string)

    # 3. Insert underscore before capital letters preceded by lowercase letters (camelCase -> snake_case)
    string = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", string)

    # 4. Convert everything to lowercase
    string = string.lower()

    # 5. Remove any duplicate underscores
    string = re.sub(r"__+", "_", string)

    # 6. Remove leading/trailing underscores
    string = string.strip("_")

    return string


def get_strip_id_from_entity_id(entity_id: str) -> str:
    """
    Extract the strip ID from an entity ID string.

    The strip ID is defined as the entity ID **up to and including the last uppercase letter**.
    All characters after the last uppercase letter are removed.

    Examples:
        "ABCX123" -> "ABCX"
        "DEFY456_extra" -> "DEFY"
        "GHIJ" -> "GHIJ"
    """
    match = re.search(r"[A-Z](?!.*[A-Z])", entity_id)
    if not match:
        raise ValueError(f"Invalid entity_id '{entity_id}': contains no uppercase letter.")

    # Retourne tout jusqu'à la position de cette majuscule (incluse)
    return entity_id[: match.end()]


# End-of-file (EOF)
