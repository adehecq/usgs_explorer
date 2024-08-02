# pylint: disable=redefined-outer-name
"""
Description: module contain the unitary tests utils module

Last modified: 2024
Author: Luc Godin
"""
import os
from tempfile import TemporaryDirectory

import pytest

from usgsxplore.api import API
from usgsxplore.utils import (
    download_browse_img,
    read_textfile,
    save_in_gfile,
    sort_strings_by_similarity,
    to_gdf,
    update_gdf_browse,
)


@pytest.fixture(scope="module")
def scenes_metadata() -> list[dict]:
    api = API(os.getenv("USGS_USERNAME"), token=os.getenv("USGS_TOKEN"))
    scenes = []
    for batch_scenes in api.batch_search("declassii", None, 10, "full", 0):
        scenes += batch_scenes
    api.logout()
    return scenes


def test_to_gdf(scenes_metadata: list[dict]) -> None:
    "Test the to_gdf function"
    gdf = to_gdf(scenes_metadata)
    assert gdf.shape[0] == 10
    assert gdf.shape[1] == 35


def test_save_in_gfile(scenes_metadata: list[dict]):
    "Test the save_in_gfile functions"
    gdf = to_gdf(scenes_metadata)

    with TemporaryDirectory() as tmpdir:
        gpkg_file = os.path.join(tmpdir, "tmp.gpkg")
        shapefile = os.path.join(tmpdir, "tmp.shp")
        geojson = os.path.join(tmpdir, "tmp.geojson")
        invalid_file = os.path.join(tmpdir, "tmp.invalid")

        save_in_gfile(gdf, gpkg_file)
        with pytest.warns(UserWarning):
            save_in_gfile(gdf, shapefile)
        save_in_gfile(gdf, geojson)
        with pytest.raises(ValueError):
            save_in_gfile(gdf, invalid_file)

        assert os.path.exists(gpkg_file)
        assert os.path.exists(shapefile)
        assert os.path.exists(geojson)
        assert not os.path.exists(invalid_file)


def test_sort_strings_by_similarity() -> None:
    "Test the sort_strings_by_similarity function"
    ref_str = "hello foo, I'm bar"
    list_str = ["hello bar, i'm foo", "hi foo, i'm bar", "every body love the sunshine", "foo foo bar bar"]
    sorted_str = sort_strings_by_similarity(ref_str, list_str)
    assert sorted_str == ["hi foo, i'm bar", "foo foo bar bar", "hello bar, i'm foo", "every body love the sunshine"]


def test_read_textfile() -> None:
    "Test the read_textfile function"
    with TemporaryDirectory() as tmpdir:
        textfile = os.path.join(tmpdir, "tmp.txt")
        with open(textfile, "w", encoding="utf-8") as file:
            file.write("#dataset=declassii\n")
            file.write("id1 # id2 id3\n")
            file.write("# id2 id3\n")
            file.write("id4\n")

        list_id = read_textfile(textfile)
        assert "id1" in list_id
        assert "id2" not in list_id and "id3" not in list_id
        assert "id4" in list_id
        assert len(list_id) == 2


def test_download_browse_img(scenes_metadata: list[dict]) -> None:
    "Test the download_browse_img function"
    gdf = to_gdf(scenes_metadata)
    url_list = gdf["browse_url"].tolist()

    with TemporaryDirectory() as tmpdir:
        dl_recap = download_browse_img(url_list, tmpdir, False)
        assert dl_recap.shape == (10, 2)
        assert len(os.listdir(tmpdir)) == 10


def test_update_gdf_browse(scenes_metadata: list[dict]) -> None:
    "Test the update_gdf_browse function"
    gdf = to_gdf(scenes_metadata)

    gdf = update_gdf_browse(gdf, "images")

    # test if the browse_path key exist in column
    gdf["browse_path"]


# End-of-file (EOF)
