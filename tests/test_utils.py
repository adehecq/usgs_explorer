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
from usgsxplore.utils import read_textfile, sort_strings_by_similarity, to_gpkg


@pytest.fixture(scope="module")
def scenes_metadata() -> list[dict]:
    api = API(os.getenv("USGSXPLORE_USERNAME"), token=os.getenv("USGSXPLORE_TOKEN"))
    scenes = []
    for batch_scenes in api.batch_search("declassii", None, 10, "full", 0):
        scenes += batch_scenes
    api.logout()
    return scenes


def test_to_gpkg(scenes_metadata: list[dict]):
    "Test the to_gpkg functions"
    with TemporaryDirectory() as tmpdir:
        gpkg_file = os.path.join(tmpdir, "tmp.gpkg")
        shapefile = os.path.join(tmpdir, "tmp.shp")
        geojson = os.path.join(tmpdir, "tmp.geojson")
        invalid_file = os.path.join(tmpdir, "tmp.invalid")

        to_gpkg(scenes_metadata, gpkg_file)
        with pytest.warns(UserWarning):
            to_gpkg(scenes_metadata, shapefile)
        to_gpkg(scenes_metadata, geojson)
        with pytest.raises(ValueError):
            to_gpkg(scenes_metadata, invalid_file)

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


# End-of-file (EOF)
