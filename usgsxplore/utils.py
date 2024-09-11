"""
Description: module contain some utils functions and class

Last modified: 2024
Author: Luc Godin
"""
import os
import warnings
from difflib import SequenceMatcher

import geopandas as gpd
import pandas as pd
import requests
from shapely import MultiPolygon, Point, Polygon
from tqdm import tqdm


def to_gdf(scenes_metadata: list[dict]) -> None:
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
            attributes.setdefault(field.get("fieldName"), []).append(field.get("value"))

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
        # here we ingore warnings that tell us all field are truncated
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=r"Normalized/laundered field name: '.+' to '.+'")
            gdf.to_file(vector_file)
    elif vector_file.endswith(".gpkg"):
        gdf.to_file(vector_file, driver="GPKG")
    elif vector_file.endswith(".geojson"):
        gdf.to_file(vector_file, driver="GeoJSON")
    else:
        raise ValueError(f"The file '{vector_file}' need to end with : .shp|.gpkg|.geojson")


def read_textfile(textfile: str) -> list[str]:
    """
    This function read a textfile and return a list of ids found in the textfile,
    without comment line

    :param textfile: path of the textfile
    """
    list_ids = []

    with open(textfile, encoding="utf-8") as file:
        # loop in other line and don't take the comment
        for line in file:
            if not line.strip().startswith("#"):
                spl = line.split("#", maxsplit=1)
                list_ids.append(spl[0].strip())
    return list_ids


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


def download_browse_img(url_list: list[str], output_dir: str, pbar: bool = True) -> pd.DataFrame:
    """
    Download all browse image with the url_list and put them into the output_dir.
    Return a recap of the downloading.

    :param url_list: list of all browse images url
    :param output_dir: output directory
    :param pbar: if True display a progress bar of the downloading
    :return: dataframe of downloading recap
    """
    # Some URLs are set to None -> remove those
    url_list_filtered = [url for url in url_list if url is not None]
    print(f"Found {len(url_list) - len(url_list_filtered)} invalid URLs -> skipping")
    url_list = url_list_filtered

    # Create a dataframe of urls
    df = pd.DataFrame({"url": url_list})
    df.set_index("url", inplace=True)
    df = df.assign(already_download=False, status=None)

    # Create a set of already downloaded files for faster lookup
    already_dl_files = {file.split(".", maxsplit=1)[0] for file in os.listdir(output_dir) if file.endswith(".jpg")}

    # Mark already downloaded files in the DataFrame
    for url in url_list:
        filename = os.path.basename(url).split(".", maxsplit=1)[0]
        if filename in already_dl_files:
            df.loc[url, "already_download"] = True

    # create a progress_bar if pbar
    if pbar:
        progress_bar = tqdm(desc="Downloading images", total=len(url_list), initial=df["already_download"].sum())

    # loop around not already_download urls and download it and save
    # status_code in the dataframe
    session = requests.Session()
    # flake8: noqa E712
    for url, row in df[df["already_download"] == False].iterrows():
        response = session.get(url)
        if response.status_code == 200:
            # get the name of the images
            filename = os.path.basename(url)

            with open(os.path.join(output_dir, filename), "wb") as f:
                f.write(response.content)
        df.loc[url, "status"] = response.status_code

        if pbar:
            progress_bar.update()
    # close the progress bar at the end of the downloading
    if pbar:
        progress_bar.close()

    # return the recap
    return df


def basename_ignore_none(path: str | None):
    """
    Return the basename of a path but ignore items with None to avoid errors for invalid browse url.
    :param path: Path to the file
    :return: basename to the file, or "none" if input is None
    """
    if path is not None:
        return os.path.basename(path)
    else:
        return "none"


def update_gdf_browse(gdf: gpd.GeoDataFrame, output_dir: str) -> gpd.GeoDataFrame:
    """
    Update the gdf given to add a new metadata "browse_path" with the browse.

    :param gdf: the geodataframe that would be modified
    :param output_dir: browse output_dir
    :return gdf
    """
    gdf = gdf.assign(browse_path=gdf["browse_url"])
    gdf["browse_path"] = gdf["browse_path"].apply(basename_ignore_none)
    gdf["browse_path"] = gdf["browse_path"].apply(lambda x: os.path.join(output_dir, x))

    return gdf


def format_table(data: list[list]) -> str:
    """
    Return a string reprentation of a 2 dimensional table

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


# End-of-file (EOF)
