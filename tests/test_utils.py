# pylint: disable=redefined-outer-name
"""
Description: module contain the unitary tests utils module

Last modified: 2024
Author: Luc Godin
"""

import gzip
import os
import shutil
import signal
import tarfile
import tempfile
from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import MagicMock

import pytest

import usgsxplore.errors as err
from usgsxplore.api import API
from usgsxplore.utils import (
    convert_response_to_gdf,
    download_browse_img,
    download_scenes,
    extract_files_in_place,
    process_download_options,
    read_textfile,
    save_in_gfile,
    sort_strings_by_similarity,
    update_gdf_browse,
)


@pytest.fixture(scope="module")
def scenes_metadata(api: API) -> list[dict]:
    scenes = []
    for batch_scenes in api.batch_search("declassii", None, 10, "full", 0):
        scenes += batch_scenes
    return scenes


def test_to_gdf(scenes_metadata: list[dict]) -> None:
    "Test the to_gdf function"
    gdf = convert_response_to_gdf(scenes_metadata)
    assert gdf.shape[0] == 10
    assert gdf.shape[1] == 35


def test_save_in_gfile(scenes_metadata: list[dict]):
    "Test the save_in_gfile functions"
    gdf = convert_response_to_gdf(scenes_metadata)

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
    list_str = [
        "hello bar, i'm foo",
        "hi foo, i'm bar",
        "every body love the sunshine",
        "foo foo bar bar",
    ]
    sorted_str = sort_strings_by_similarity(ref_str, list_str)
    assert sorted_str == [
        "hi foo, i'm bar",
        "foo foo bar bar",
        "hello bar, i'm foo",
        "every body love the sunshine",
    ]


def test_read_textfile() -> None:
    "Test the read_textfile function"
    with TemporaryDirectory() as tmpdir:
        textfile = os.path.join(tmpdir, "tmp.txt")
        with open(textfile, "w", encoding="utf-8") as file:
            file.write("#dataset=declassii\n")
            file.write("id1 # id2 id3\n")
            file.write("# id2 id3\n")
            file.write("id4\n")

        dataset, list_id = read_textfile(textfile)
        assert dataset == "declassii"
        assert "id1" in list_id
        assert "id2" not in list_id and "id3" not in list_id
        assert "id4" in list_id
        assert len(list_id) == 2


def test_download_browse_img(scenes_metadata: list[dict]) -> None:
    "Test the download_browse_img function"
    gdf = convert_response_to_gdf(scenes_metadata)
    url_list = gdf["browse_url"].tolist()

    with TemporaryDirectory() as tmpdir:
        dl_recap = download_browse_img(url_list, tmpdir, False)
        assert dl_recap.shape == (10, 2)
        assert len(os.listdir(tmpdir)) == 10


def test_update_gdf_browse(scenes_metadata: list[dict]) -> None:
    "Test the update_gdf_browse function"
    gdf = convert_response_to_gdf(scenes_metadata)

    gdf = update_gdf_browse(gdf, "images")

    # test if the browse_path key exist in column
    gdf["browse_path"]


# ------------------------------------------------------------------------------------------------------
#                                       TestDownloadScenes
# ------------------------------------------------------------------------------------------------------
class TestDownloadScenes:
    def test_download_scenes(self):
        with mock.patch("os.makedirs") as mock_os_makedirs:
            with mock.patch("requests.Session.get") as mock_requests_get:
                with mock.patch("tqdm.tqdm") as mock_tqdm:
                    scenes = [
                        {
                            "entityId": "scene1",
                            "url": "http://example.com/scene1",
                            "filesize": 1000,
                        },
                        {
                            "entityId": "scene2",
                            "url": "http://example.com/scene2",
                            "filesize": 2000,
                        },
                    ]

                    output_dir = "./output"
                    max_threads = 2
                    show_progress = False

                    # Simulate a response for 'requests.get'
                    mock_response = MagicMock()
                    mock_response.raise_for_status = MagicMock()
                    mock_response.headers = {
                        "Content-Disposition": 'attachment; filename="test_file.tif"'
                    }
                    mock_response.iter_content = MagicMock(return_value=[b"test data"])
                    mock_requests_get.return_value = mock_response

                    # Run the function
                    download_scenes(scenes, output_dir, max_threads, show_progress)

                    # Check if os.makedirs was called to create the output directory
                    mock_os_makedirs.assert_called_with(output_dir, exist_ok=True)

                    # Check if requests.get was called for each scene's URL
                    for scene in scenes:
                        mock_requests_get.assert_any_call(
                            scene["url"], stream=True, timeout=30
                        )

                    # Verify that the progress bar was not updated since show_progress is False
                    mock_tqdm.assert_not_called()

    def test_overwrite_enabled(self):
        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("requests.Session.get") as mock_requests_get:
                scenes = [
                    {
                        "entityId": "scene1",
                        "url": "http://example.com/scene1",
                        "filesize": 1000,
                    },
                ]

                output_dir = "./output"
                show_progress = False

                # Run the function
                download_scenes(
                    scenes, output_dir, max_threads=2, show_progress=show_progress
                )

                # Verify that requests.get was called to download the file again
                mock_requests_get.assert_any_call(
                    "http://example.com/scene1", stream=True, timeout=30
                )

    def test_interrupt_download(self):
        # Simulate a SIGINT signal interrupt during the download (e.g., Ctrl+C)
        with mock.patch("sys.exit") as mock_exit:
            with mock.patch("requests.Session.get") as mock_requests_get:
                scenes = [
                    {
                        "entityId": "scene1",
                        "url": "http://example.com/scene1",
                        "filesize": 1000,
                    },
                ]
                output_dir = "./output"
                show_progress = False

                # Simulate the response object for 'requests.get' mock
                mock_response = MagicMock()
                mock_response.raise_for_status = MagicMock()
                mock_response.headers = {
                    "Content-Disposition": 'attachment; filename="test_file.tif"'
                }
                mock_response.iter_content = MagicMock(return_value=[b"test data"])
                mock_requests_get.return_value = mock_response

                # Prepare a signal handler mock to capture the signal interruption
                signal_handler = MagicMock()

                # Patch the signal handler inside the function
                with mock.patch("signal.signal", side_effect=signal_handler):
                    # Run the download_scenes in a separate thread to simulate download and interruption
                    download_scenes(
                        scenes, output_dir, max_threads=2, show_progress=show_progress
                    )

                    # Raise the SIGINT signal to simulate an interruption (like Ctrl+C)
                    signal.raise_signal(signal.SIGINT)

                    # Ensure that the signal handler was called
                    signal_handler.assert_called_with(signal.SIGINT, mock.ANY)

            # Ensure sys.exit was called due to the interruption
            mock_exit.assert_called_once()


# ------------------------------------------------------------------------------------------------------
#                                       TestProcessDownloadOptions
# ------------------------------------------------------------------------------------------------------


class TestProcessDownloadOptions:
    @pytest.fixture
    def sample_options(self):
        return [
            {
                "available": True,
                "entityId": 1,
                "productCode": "A1",
                "productName": "Produit A1",
            },
            {
                "available": True,
                "entityId": 1,
                "productCode": "A2",
                "productName": "Produit A2",
            },
            {
                "available": True,
                "entityId": 2,
                "productCode": "B1",
                "productName": "Produit B1",
            },
            {
                "available": False,
                "entityId": 3,
                "productCode": "C1",
                "productName": "Produit C1",
            },
        ]

    def test_no_available_products(self):
        options = [
            {
                "available": False,
                "entityId": 1,
                "productCode": "A1",
                "productName": "Produit A1",
            }
        ]
        with pytest.raises(err.DownloadOptionsError, match="No product available"):
            process_download_options(options)

    def test_multiple_products_without_choice(self, sample_options):
        with pytest.raises(err.DownloadOptionsError, match="Multiple products found"):
            process_download_options(sample_options)

    def test_invalid_product_number(self, sample_options):
        with pytest.raises(err.DownloadOptionsError, match="Invalid product number"):
            process_download_options(sample_options, product_number=10)

    def test_valid_selection_first_product(self, sample_options):
        result = process_download_options(sample_options, product_number=0)
        assert all(opt["productCode"] == "A1" for opt in result)
        assert len(result) == 1

    def test_valid_selection_second_product(self, sample_options):
        result = process_download_options(sample_options, product_number=1)
        assert all(opt["productCode"] == "A2" for opt in result)
        assert len(result) == 1

    def test_single_product_case(self):
        options = [
            {
                "available": True,
                "entityId": 1,
                "productCode": "X1",
                "productName": "Produit X",
            }
        ]
        result = process_download_options(options)
        assert result == options


# ------------------------------------------------------------------------------------------------------
#                                       TestExtractFilesInPlace
# ------------------------------------------------------------------------------------------------------


class TestExtractFilesInPlace:
    @pytest.fixture
    def temp_dir(self):
        dirpath = tempfile.mkdtemp()
        yield dirpath
        shutil.rmtree(dirpath)

    def create_gz_file(self, directory, filename, content=b"test content"):
        file_path = os.path.join(directory, filename)
        with gzip.open(file_path, "wb") as f:
            f.write(content)
        return file_path

    def create_tar_gz_file(self, directory, filename, internal_files):
        tar_path = os.path.join(directory, filename)
        with tarfile.open(tar_path, "w:gz") as tar:
            for name, data in internal_files.items():
                temp = tempfile.NamedTemporaryFile(delete=False)
                temp.write(data)
                temp.close()
                tar.add(temp.name, arcname=name)
                os.unlink(temp.name)
        return tar_path

    def test_extract_gz_file(self, temp_dir):
        self.create_gz_file(temp_dir, "test.gz", b"hello world")
        extract_files_in_place(temp_dir, show_progress=False)
        extracted_file = os.path.join(temp_dir, "test")
        assert os.path.exists(extracted_file)
        with open(extracted_file, "rb") as f:
            assert f.read() == b"hello world"

    def test_extract_tar_gz_file(self, temp_dir):
        self.create_tar_gz_file(
            temp_dir, "archive.tar.gz", {"file1.txt": b"data1", "file2.txt": b"data2"}
        )
        extract_files_in_place(temp_dir, show_progress=False)
        assert os.path.exists(os.path.join(temp_dir, "file1.txt"))
        assert os.path.exists(os.path.join(temp_dir, "file2.txt"))

    def test_remove_gz_files(self, temp_dir):
        gz_path = self.create_gz_file(temp_dir, "toremove.gz", b"remove me")
        extract_files_in_place(temp_dir, show_progress=False, remove_gz=True)
        assert not os.path.exists(gz_path)

    def test_keep_gz_files(self, temp_dir):
        gz_path = self.create_gz_file(temp_dir, "tokeep.gz", b"keep me")
        extract_files_in_place(temp_dir, show_progress=False, remove_gz=False)
        assert os.path.exists(gz_path)

    def test_ignore_non_matching_files(self, temp_dir):
        non_compressed = os.path.join(temp_dir, "not_a_gz.txt")
        with open(non_compressed, "w") as f:
            f.write("just a text file")
        extract_files_in_place(temp_dir, show_progress=False)
        # Should not raise or affect the file
        assert os.path.exists(non_compressed)


# End-of-file (EOF)
