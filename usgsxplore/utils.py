"""
Description: module contain some utils functions and class

Last modified: 2024
Author: Luc Godin
"""
import os

import geopandas as gpd
from shapely import MultiPolygon, Polygon


def to_gpkg(scenes_metadata: list[dict], geo_file: str = "scenes.gpkg") -> None:
    """
    This method convert the file scenes.jsonl into a geodataframe with the spatialCoverage for the geometry

    :return: GeoDataFrame to generate a geopackage
    """
    geometries = []
    attributes = {}

    img_dir = os.path.join(os.path.dirname(geo_file), "browse-images")

    # loop in every line of the scenes file
    for scene in scenes_metadata:
        geom_type = scene["spatialCoverage"]["type"]
        if geom_type == "Polygon":
            geometries.append(Polygon(scene["spatialCoverage"]["coordinates"][0]))
        elif geom_type == "MultiPolygon":
            geometries.append(MultiPolygon(scene["spatialCoverage"]["coordinates"]))
        else:
            continue

        # add all metadata attribute
        for field in scene.get("metadata"):
            attributes.setdefault(field.get("fieldName"), []).append(field.get("value"))

        if len(scene["browse"]) > 0:
            attributes.setdefault("browse_path", []).append(
                os.path.join(os.path.abspath(img_dir), os.path.basename(scene["browse"][0]["browsePath"]))
            )
            attributes.setdefault("browse_url", []).append(scene["browse"][0]["browsePath"])
        else:
            attributes.setdefault("browse_path", []).append(None)
            attributes.setdefault("browse_url", []).append(None)

    # create geodataframe with attributes and geometries
    gdf = gpd.GeoDataFrame(data=attributes, geometry=geometries)

    # save the geodataframe in a geospatial file
    if geo_file.endswith(".shp"):
        gdf.to_file(geo_file)
    elif geo_file.endswith(".gpkg"):
        gdf.to_file(geo_file, driver="GPKG")
    elif geo_file.endswith(".geojson"):
        gdf.to_file(geo_file, driver="GeoJSON")
    else:
        raise ValueError(f"The file '{geo_file}' need to end with : .shp|.gpkg|.geojson")


# End-of-file (EOF)
