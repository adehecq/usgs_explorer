"""
Module: test_filter.py
Author: godinlu
Date: 25
Description: Unit test for filter
"""

import os
from tempfile import TemporaryDirectory

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

import usgsxplore.errors as errors
import usgsxplore.filter as filter


def test_coordinate():
    "Test the coordinate class"
    lon, lat = 17.5, 18.0
    coord = filter.Coordinate(lon, lat)
    assert coord["longitude"] == lon
    assert coord["latitude"] == lat


def test_geojson():
    "Test the geojson class"
    shape = {
        "type": "Polygon",
        "coordinates": [
            [
                [-87.90681, 41.972731],
                [-87.629799, 41.972731],
                [-87.629799, 42.000907],
                [-87.90681, 42.000907],
                [-87.90681, 41.972731],
            ]
        ],
    }
    geojson = filter.GeoJson(shape)
    assert geojson["type"] == "Polygon"
    assert isinstance(geojson["coordinates"], list)
    assert len(geojson["coordinates"][0]) >= 4  # a polygon need to have more than  4 points
    assert geojson["coordinates"][0][0] == geojson["coordinates"][0][-1]  # check if the polygon are closed


def test_spatial_filter_geojson():
    "Test the SpatialFilterGeoJSON class"
    shape = {
        "type": "Polygon",
        "coordinates": [
            [
                [-87.90681, 41.972731],
                [-87.629799, 41.972731],
                [-87.629799, 42.000907],
                [-87.90681, 42.000907],
                [-87.90681, 41.972731],
            ]
        ],
    }
    sfg = filter.SpatialFilterGeoJSON(shape)
    assert sfg["filterType"] == "geojson"
    assert isinstance(sfg["geoJson"], filter.GeoJson)


def test_spatial_filter_from_file():
    "Test the SpatialFilterGeoJSON.from_file method"
    coords = [
        [-87.90681, 41.972731],
        [-87.629799, 41.972731],
        [-87.629799, 42.000907],
        [-87.90681, 42.000907],
        [-87.90681, 41.972731],
    ]
    poly = Polygon(coords)
    geometry = gpd.GeoSeries([poly], crs="EPSG:4326")
    gdf = gpd.GeoDataFrame({"geometry": geometry})
    with TemporaryDirectory() as tmp_dir:
        gdf.to_file(os.path.join(tmp_dir, "shape.geojson"), driver="GeoJSON")
        sfg = filter.SpatialFilterGeoJSON.from_file(os.path.join(tmp_dir, "shape.geojson"))
        assert sfg["filterType"] == "geojson"
        assert isinstance(sfg["geoJson"], filter.GeoJson)


def test_spatial_filter_mbr():
    "Test the SpatialFilterMbr class"
    xmin, ymin, xmax, ymax = 1, 2, 3, 4
    sfm = filter.SpatialFilterMbr(xmin, ymin, xmax, ymax)
    assert sfm["filterType"] == "mbr"
    assert sfm["lowerLeft"] == filter.Coordinate(xmin, ymin)
    assert sfm["upperRight"] == filter.Coordinate(xmax, ymax)


def test_acquisition_filter():
    "Test the AcquisitionFilter class"
    start, end = "2010-01-01", "2010-01-31"
    af = filter.AcquisitionFilter(start, end)
    assert af["start"] == start and af["end"] == end

    with pytest.raises(errors.AcquisitionFilterError):
        filter.AcquisitionFilter("20/11/2002", "20/11/2003")


def test_cloud_cover_filter():
    "Test the CloudCoverFilter class"
    ccf = filter.CloudCoverFilter(10, 50, True)
    assert ccf["min"] == 10
    assert ccf["max"] == 50
    assert ccf["includeUnknown"]


def test_scene_filter():
    "Test the scene_filter"
    sf = filter.SceneFilter.from_args(location=(18, 18), months=[1, 2, 3])
    assert isinstance(sf["spatialFilter"], filter.SpatialFilterMbr)
    assert sf["seasonalFilter"] == [1, 2, 3]

    sf = filter.SceneFilter.from_args(date_interval=("2020-05-25", "2021-05-25"), max_cloud_cover=70)
    assert isinstance(sf["acquisitionFilter"], filter.AcquisitionFilter)
    assert isinstance(sf["cloudCoverFilter"], filter.CloudCoverFilter)

    sf = filter.SceneFilter.from_args(meta_filter="field=value")
    assert isinstance(sf["metadataFilter"], filter.MetadataFilter)


# End-of-file (EOF)
