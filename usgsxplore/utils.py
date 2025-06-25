"""
Description: module contain some utils functions and class

Last modified: 2024
Author: Luc Godin
"""

import gzip
import os
import signal
import subprocess
import sys
import tarfile
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from shutil import copyfileobj
from urllib.parse import urlparse

import folium
import geopandas as gpd
import pandas as pd
import requests
from shapely import MultiPolygon, Point, Polygon
from tqdm import tqdm

from usgsxplore.errors import DownloadOptionsError


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
            attributes.setdefault("browse_url", []).append(
                scene["browse"][0]["browsePath"]
            )
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
            warnings.filterwarnings(
                "ignore", message=r"Normalized/laundered field name: '.+' to '.+'"
            )
            gdf.to_file(vector_file)
    elif vector_file.endswith(".gpkg"):
        gdf.to_file(vector_file, driver="GPKG")
    elif vector_file.endswith(".geojson"):
        gdf.to_file(vector_file, driver="GeoJSON")
    else:
        raise ValueError(
            f"The file '{vector_file}' need to end with : .shp|.gpkg|.geojson"
        )


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
    similarity_scores = [
        SequenceMatcher(None, ref_str, str_).ratio() for str_ in list_str
    ]

    # Sort list_str based on similarity scores
    sorted_list_str = [
        str_ for _, str_ in sorted(zip(similarity_scores, list_str), reverse=True)
    ]

    return sorted_list_str


def download_browse_img(
    url_list: list[str], output_dir: str, pbar: bool = True
) -> pd.DataFrame:
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
    already_dl_files = {
        file.split(".", maxsplit=1)[0]
        for file in os.listdir(output_dir)
        if file.endswith(".jpg")
    }

    # Mark already downloaded files in the DataFrame
    for url in url_list:
        filename = os.path.basename(url).split(".", maxsplit=1)[0]
        if filename in already_dl_files:
            df.loc[url, "already_download"] = True

    # create a progress_bar if pbar
    if pbar:
        progress_bar = tqdm(
            desc="Downloading images",
            total=len(url_list),
            initial=df["already_download"].sum(),
        )

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
    Return a string representation of a 2 dimensional table

    :param data: 2 dimensional table
    :return: string representation
    """
    table_str = ""
    col_widths = [max(len(str(item)) for item in col) for col in zip(*data)]

    # consider the first line like a header
    header = (
        "   ".join(f"{str(item):<{col_widths[i]}}" for i, item in enumerate(data[0]))
        + "\n"
    )
    table_str += header

    # construct other line
    for row in data[1:]:
        table_str += (
            " | ".join(f"{str(item):<{col_widths[i]}}" for i, item in enumerate(row))
            + "\n"
        )

    return table_str


def convert_response_to_df(scenes_metadata: list[dict]) -> pd.DataFrame:
    """
    Convert scenes metadata into a pandas DataFrame (without geometry).

    :param scenes_metadata: list of scene dictionaries (e.g., from scenes.jsonl)
    :return: DataFrame with metadata and browse_url
    """
    attributes = {}

    for scene in scenes_metadata:
        # add all metadata attributes
        for field in scene.get("metadata", []):
            attributes.setdefault(field.get("fieldName"), []).append(field.get("value"))

        # add browse_url field
        if len(scene.get("browse", [])) > 0:
            attributes.setdefault("browse_url", []).append(
                scene["browse"][0].get("browsePath")
            )
        else:
            attributes.setdefault("browse_url", []).append(None)

    return pd.DataFrame(data=attributes)


def process_download_options(
    download_options: list[dict], product_number: int | None = None
) -> list[dict] | None:
    """
    Filters and selects download options based on availability and product selection.

    Args:
        download_options (list[dict]): A list of download option dictionaries,
            each containing at least 'available', 'entityId', 'productCode', and 'productName' keys.
        product_number (int | None, optional): Index of the product to select if multiple are found.
            If None and multiple products are found, an exception is raised.

    Returns:
        list[dict]: A list of download options matching the selected product code.

    Raises:
        DownloadOptionsError: If no available products are found, multiple options require a choice,
                              or the given product_number is invalid.
    """

    # Filter only the available options
    available_options = [opt for opt in download_options if opt.get("available")]

    if not available_options:
        raise DownloadOptionsError("No product available")

    # Use the entityId of the first available product to group similar products
    entity_id = available_options[0]["entityId"]
    product_list = []

    # Collect all options that belong to the same entityId group
    for opt in available_options:
        if entity_id != opt["entityId"]:
            break
        product_list.append(opt)

    # Handle case where multiple products are found
    if len(product_list) > 1:
        if product_number is None:
            product_names = "\n".join(
                f" - {i} : {p['productName']}" for i, p in enumerate(product_list)
            )
            raise DownloadOptionsError(
                f"Multiple products found, you need to choose one:\n{product_names}"
            )
        if not (0 <= product_number < len(product_list)):
            product_names = "\n".join(
                f" - {i} : {p['productName']}" for i, p in enumerate(product_list)
            )
            raise DownloadOptionsError(
                f"Invalid product number: {product_number}, choose one of:\n{product_names}"
            )
        selected_code = product_list[product_number]["productCode"]
    else:
        selected_code = product_list[0]["productCode"]

    return [opt for opt in available_options if opt["productCode"] == selected_code]


def download_scenes(
    scenes: list[dict],
    output_dir: str = ".",
    max_threads: int = 5,
    show_progress: bool = True,
):
    """
    Download files from a list of dicts with 'entityId', 'url' and 'filesize'.
    The filename will be: {entityId}.{extension}

    :param scenes: List of dicts like {'entityId': str, 'url': str, 'filesize': int}
    :param output_dir: Directory to save the downloaded files
    :param max_threads: Number of concurrent download threads
    :param show_progress: Whether to display a progress bar
    :return: None
    """
    os.makedirs(output_dir, exist_ok=True)
    session = requests.Session()

    # Total size of all files
    total_size = sum(int(item.get("filesize", 0)) for item in scenes)
    progress_bar = (
        tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            desc=f"Downloading (0/{len(scenes)})",
        )
        if show_progress
        else None
    )

    tqdm.set_lock(threading.Lock())  # Make tqdm thread-safe

    # Create a stop event that can be used to interrupt the download
    stop_event = threading.Event()

    def download(item: dict):
        url = item.get("url")
        entity_id = item.get("entityId")
        try:
            with session.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()

                # get the file name from response header
                content_disposition = r.headers.get("Content-Disposition")
                filename = content_disposition.split("filename=")[1].strip('"')
                filename = filename.replace(filename.split(".")[0], entity_id)
                file_path = os.path.join(output_dir, filename)

                with open(file_path, "wb") as f:
                    for chunk in r.iter_content(
                        chunk_size=10000 * 1024
                    ):  # block size of 10 Mo
                        if (
                            stop_event.is_set()
                        ):  # Check if stop_event has been set to stop download
                            os.remove(file_path)
                            break

                        f.write(chunk)
                        if progress_bar:
                            progress_bar.update(len(chunk))
            return filename
        except Exception as e:
            return f"Error downloading {url}: {e}"

    def signal_handler(sig, frame):
        print("\nDownload interrupted.")
        stop_event.set()  # Set the stop event to signal all threads to stop
        if progress_bar:
            progress_bar.close()  # Ensure the progress bar is closed properly
        sys.exit(0)  # Exit gracefully

    signal.signal(signal.SIGINT, signal_handler)

    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        for i, result in enumerate(executor.map(download, scenes), start=1):
            if progress_bar:
                progress_bar.set_description(f"Downloading ({i}/{len(scenes)})")

    if progress_bar:
        progress_bar.close()


def extract_files_in_place(
    gz_directory: str,
    show_progress: bool = True,
    remove_gz: bool = True,
    patterns: list[str] = [".gz", ".tgz", ".tar.gz"],
    max_workers: int = 4,
) -> None:
    """
    Extract all files in the specified folder that match the given pattern (e.g., ".gz"), using multithreading.

    :param gz_directory: Directory containing the compressed files
    :param show_progress: Display a progress bar if True
    :param remove_gz: Remove original .gz files after extraction if True
    :param patterns: List of file extensions to match (e.g., [".gz", ".tgz"]).
    :param max_workers: Number of threads to use for parallel extraction
    """
    files = [
        f
        for f in os.listdir(gz_directory)
        if any(f.lower().endswith(p) for p in patterns)
    ]

    def extract_file(filename: str):
        file_path = os.path.join(gz_directory, filename)
        try:
            if tarfile.is_tarfile(file_path):  # for .tar.gz / .tgz
                with tarfile.open(file_path, "r:*") as tar:
                    tar.extractall(path=gz_directory)
                if remove_gz:
                    os.remove(file_path)
                return f"Extracted archive: {filename}"
            else:  # for .gz single-file
                output_path = os.path.splitext(file_path)[0]
                with (
                    gzip.open(file_path, "rb") as f_in,
                    open(output_path, "wb") as f_out,
                ):
                    copyfileobj(f_in, f_out)
                if remove_gz:
                    os.remove(file_path)
                return f"Extracted file: {filename}"
        except Exception as e:
            return f"Error extracting {filename}: {e}"

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(extract_file, f): f for f in files}
        if show_progress:
            for _ in tqdm(
                as_completed(futures),
                total=len(futures),
                desc="Extracting",
                unit="file",
            ):
                pass
        else:
            for _ in as_completed(futures):
                pass


# End-of-file (EOF)
