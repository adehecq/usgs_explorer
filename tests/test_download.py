# pylint: disable=redefined-outer-name
"""
Description: module contain the unitary tests for the download

Last modified: 2024
Author: Luc Godin
"""

import os
import time
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from usgsxplore.api import API, ScenesDownloader, ScenesNotFound, USGSInvalidDataset


@pytest.fixture(scope="module")
def api():
    _api = API(os.getenv("USGS_USERNAME"), token=os.getenv("USGS_TOKEN"))
    yield _api
    _api.logout()


def test_dataset_not_available(api: API):
    "Test error when the dataset is not valid"
    entity_ids = ["this_is_not_valid"]
    with TemporaryDirectory() as tmpdir:
        with pytest.raises(USGSInvalidDataset):
            api.download("unknown_dataset", entity_ids, tmpdir, pbar_type=True)


def test_scenes_not_founds(api: API):
    "Test error when no scenes are found in the dataset"
    entity_ids = ["this_is_not_valid"]
    with TemporaryDirectory() as tmpdir:
        with pytest.raises(ScenesNotFound):
            api.download("declassii", entity_ids, tmpdir, pbar_type=True)


def test_scenes_not_available(api: API):
    "Test that no file are download when scenes are not available"
    entity_ids = ["DZB1216-500523L001001"]
    with TemporaryDirectory() as tmpdir:
        api.download("declassii", entity_ids, tmpdir, pbar_type=True)
        assert len(os.listdir(tmpdir)) == 0


def test_landsat_tm_c2_l1(api) -> None:
    "Test the API.download method with some landsat scenes"
    with TemporaryDirectory() as tmp_dir:
        with patch.object(ScenesDownloader, "wait_all_thread") as mock_wait_all_thread:
            api.download("landsat_tm_c2_l1", ["LT50380372012126EDC00"], tmp_dir, pbar_type=0)

            time.sleep(2)
            assert os.path.exists(os.path.join(tmp_dir, "LT05_L1TP_038037_20120505_20200820_02_T1.tar"))
            mock_wait_all_thread.assert_called_once()


def test_declassii(api) -> None:
    "Test the API.download method with some declassii scenes"
    with TemporaryDirectory() as tmp_dir:
        with patch.object(ScenesDownloader, "wait_all_thread") as mock_wait_all_thread:
            api.download("declassii", ["DZB1216-500525L001001"], tmp_dir, pbar_type=0)
            time.sleep(2)
            assert os.path.exists(os.path.join(tmp_dir, "DZB1216-500525L001001.tgz"))
            mock_wait_all_thread.assert_called_once()


def test_corona2(api) -> None:
    "Test the API.download method with some declassii scenes"
    with TemporaryDirectory() as tmp_dir:
        with patch.object(ScenesDownloader, "wait_all_thread") as mock_wait_all_thread:
            api.download("corona2", ["DS1117-2086DA003"], tmp_dir, pbar_type=0)
            time.sleep(2)
            assert os.path.exists(os.path.join(tmp_dir, "DS1117-2086DA003.tgz"))
            mock_wait_all_thread.assert_called_once()


# End-of-file (EOF)
