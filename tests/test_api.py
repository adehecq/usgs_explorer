# pylint: disable=protected-access
# pylint: disable=wrong-import-position
"""
Description: module contain the unitary tests for classes: API, ScenesDownloader, all filter classes

Last modified: 2024
Author: Luc Godin
"""

import datetime
import os
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pytest

import usgsxplore.errors as err
import usgsxplore.filter as filt
from usgsxplore.api import API


def test_login(api: API):
    "Test the login to the api"
    assert api.session.headers.get("X-Auth-Token")


def test_login_error():
    "Test the error of the login"
    with pytest.raises(err.USGSAuthenticationError):
        API("bad_username", "bad_token")


def test_get_scene_id(api: API):
    "Test the convert of display_id to entity_id"
    product_ids = [
        "LT05_L1TP_038037_20120505_20200820_02_T1",
        "LT05_L1TP_031033_20120504_20200820_02_T1",
    ]
    scene_ids = api.get_entity_id(product_ids, dataset="landsat_tm_c2_l1")
    assert scene_ids == ["LT50380372012126EDC00", "LT50310332012125EDC00"]


def test_get_entity_id(api: API):
    "Test the convert of entity id to display id"
    entity_id = "LT50380372012126EDC00"
    display_id = api.get_display_id(entity_id, dataset="landsat_tm_c2_l1")
    assert display_id == "LT05_L1TP_038037_20120505_20200820_02_T1"


def test_scene_search(api: API):
    "Test the scene search method"
    scene_filter = filt.SceneFilter.from_args(
        date_interval=("1900-01-01", "2024-08-01")
    )
    result = api.scene_search(
        "landsat_tm_c2_l1", scene_filter, max_results=1, metadata_type="summary"
    )

    assert result["recordsReturned"] == 1
    assert 2900000 <= result["totalHits"] <= 3000000  # the totalHits can changed
    assert result["startingNumber"] == 1
    assert len(result["results"][0]["metadata"]) > 0


def test_batch_search(api: API):
    "Test the batch search method"
    max_results = 100
    i = 0

    for scenes_batch in api.batch_search(
        "declassii",
        max_results=max_results,
        metadata_type="summary",
        use_tqdm=False,
    ):
        assert len(scenes_batch) == max_results
        i += 1


def test_search(api: API):
    "Test the search method"
    scenes = api.search("declassii", location=(2.2, 46.23), meta_filter="camera=L")
    assert len(scenes) == 19

    scenes = api.search(
        "landsat_tm_c2_l1",
        bbox=(5.7074, 45.1611, 5.7653, 45.2065),
        date_interval=("2010-01-01", "2019-12-31"),
    )
    assert len(scenes) == 27


def test_get_download_links_aero(api: API):
    "Test the get_download_links on aerial_combin"
    dataset = "aerial_combin"
    entity_ids = ["ARBCSRD00010006", "ARBCSRD00010007"]
    label = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # product number = 0 for medium resolution
    urls = list(
        api.get_download_links(dataset, entity_ids, product_number=0, label=label)
    )

    assert len(urls) == 2
    assert isinstance(urls[0]["url"], str)
    assert isinstance(urls[0]["entityId"], str)
    assert isinstance(urls[0]["filesize"], int)


def test_get_download_links_kh9(api: API):
    "Test the get_download_links on aerial_combin"
    dataset = "declassii"
    entity_ids = ["DZB1216-500280L001001", "DZB1216-500280L006001"]
    label = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # product number = 0 for medium resolution
    urls = list(api.get_download_links(dataset, entity_ids, label=label))

    assert len(urls) == 2
    assert isinstance(urls[0]["url"], str)
    assert isinstance(urls[0]["entityId"], str)
    assert isinstance(urls[0]["filesize"], int)


def test_download(api: API):
    with (
        patch("datetime.datetime") as mock_datetime,
        patch("os.path.exists", return_value=False),
        patch("usgsxplore.api.download_scenes") as mock_download_scenes,
        patch("usgsxplore.api.extract_files_in_place") as mock_extract_files,
    ):
        # Fixer datetime pour rendre le test déterministe (optionnel)
        mock_datetime.now.return_value.strftime.return_value = "20250425_123456"

        # Simuler get_download_links
        api.get_download_links = MagicMock(return_value=["http://mock_url/file1.tif"])

        # Appel de la méthode
        api.download(
            dataset="mock_dataset",
            entity_ids=["ENTITY1"],
            output_dir="mock_output",
            verbose=True,
        )

        # Vérifications
        api.get_download_links.assert_called_once()
        mock_download_scenes.assert_called_once_with(
            ["http://mock_url/file1.tif"], "mock_output", 5, True
        )
        mock_extract_files.assert_called_once_with("mock_output", True, max_workers=5)


def test_download_calibration_report(api: API):
    dataset = "aerial_combin"
    entity_id = "AR1SWJN00010153"

    with TemporaryDirectory() as tmpdir:
        api.download_calibration_report(dataset, entity_id, tmpdir)
        assert os.path.exists(os.path.join(tmpdir, "Report_RT-R_575.pdf"))


# End-of-file (EOF)
