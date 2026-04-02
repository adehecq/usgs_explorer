"""
Description: module contain some utils functions and class

Last modified: 2024
Author: Luc Godin
"""

import re
import warnings
from difflib import SequenceMatcher

import folium
import geopandas as gpd
from shapely import MultiPolygon, Point, Polygon


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


def save_in_html(gdf: gpd.GeoDataFrame, html_file: str = "scenes.html") -> None:
    """This function save the geodataframe into an html file for quick visualisation.
    It use folium.

    Args:
        gdf (gpd.GeoDataFrame): geodataframe that will be saved
        html_file (str, optional): output html file. Defaults to "scenes.html".
    """
    if not html_file.endswith(".html"):
        raise ValueError(f"The file '{html_file}' need to be an html file.")
    # calculate the center of the map
    gdf["centroid"] = gdf.to_crs(epsg=3857).geometry.centroid.to_crs(epsg=4326)
    center = gdf["centroid"].y.mean(), gdf["centroid"].x.mean()

    m = folium.Map(location=center, zoom_start=3)
    first_col_name = gdf.columns[0]

    # add footprint on the map
    for _, row in gdf.iterrows():
        if not row.geometry.geom_type == "Point":
            # create a popup to visualise the browse_img on click
            url = row["browse_url"]
            popup = folium.Popup(f'<img src="{url}" width="200px">', max_width=250)
            folium.GeoJson(
                row.geometry,
                tooltip=f"{first_col_name}: {row[first_col_name]}",
                popup=popup,
            ).add_to(m)

    m.save(html_file)


def read_textfile(textfile: str) -> tuple[str | None, list[str]]:
    """
    This function read a textfile and return a list of ids found in the textfile,
    without comment line

    :param textfile: path of the textfile
    """
    list_ids = []
    dataset = None

    with open(textfile, encoding="utf-8") as file:
        first_line = file.readline().strip()
        if first_line.startswith("#"):
            spl = first_line.split("=", maxsplit=1)
            if len(spl) == 2 and "dataset" in spl[0]:
                dataset = spl[1].strip()

        # loop in other line and don't take the comment
        for line in file:
            if not line.strip().startswith("#"):
                spl = line.split("#", maxsplit=1)
                list_ids.append(spl[0].strip())
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
    header = "   ".join(f"{str(item):<{col_widths[i]}}" for i, item in enumerate(data[0])) + "\n"
    table_str += header

    # construct other line
    for row in data[1:]:
        table_str += " | ".join(f"{str(item):<{col_widths[i]}}" for i, item in enumerate(row)) + "\n"

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
