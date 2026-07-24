# pylint: disable=redefined-outer-name
"""
Description: module contain the unitary tests utils module

Last modified: 2024
Author: Luc Godin
"""

import gzip
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import usgsxplore.errors as err
from usgsxplore.scene_downloader import FileExtractor, ProductSelector
from usgsxplore.utils import (
    read_textfile,
    sort_strings_by_similarity,
)


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


# ------------------------------------------------------------------------------------------------------
#                                       TestProcessDownloadOptions
# ------------------------------------------------------------------------------------------------------


class TestProductSelector:
    @pytest.fixture
    def sample_options(self):
        return [
            {"available": True, "entityId": 1, "id": "ID_A1", "productCode": "A1", "productName": "Produit A1"},
            {"available": True, "entityId": 1, "id": "ID_A2", "productCode": "A2", "productName": "Produit A2"},
            {"available": True, "entityId": 2, "id": "ID_B1", "productCode": "B1", "productName": "Produit B1"},
            {"available": False, "entityId": 3, "id": "ID_C1", "productCode": "C1", "productName": "Produit C1"},
        ]

    def test_no_available_products(self):
        options = [{"available": False, "entityId": 1, "id": "X", "productCode": "A1", "productName": "Produit A1"}]
        with pytest.raises(err.DownloadOptionsError, match="No product available"):
            ProductSelector().select(options)

    def test_multiple_products_without_choice(self, sample_options):
        with pytest.raises(err.DownloadOptionsError, match="Multiple products available"):
            ProductSelector().select(sample_options)

    def test_invalid_product_number(self, sample_options):
        with pytest.raises(err.DownloadOptionsError, match="Invalid product_number"):
            ProductSelector().select(sample_options, product_number=10)

    def test_valid_selection_first_product(self, sample_options):
        result = ProductSelector().select(sample_options, product_number=0)
        assert len(result) == 1
        assert all(p.product_name == "Produit A1" for p in result)

    def test_valid_selection_second_product(self, sample_options):
        result = ProductSelector().select(sample_options, product_number=1)
        assert len(result) == 1
        assert all(p.product_name == "Produit A2" for p in result)

    def test_single_product_case(self):
        options = [{"available": True, "entityId": 1, "id": "ID_X1", "productCode": "X1", "productName": "Produit X"}]
        result = ProductSelector().select(options)
        assert len(result) == 1
        assert result[0].entity_id == 1
        assert result[0].product_id == "ID_X1"
        assert result[0].product_name == "Produit X"


# ------------------------------------------------------------------------------------------------------
#                                       TestExtractFilesInPlace
# ------------------------------------------------------------------------------------------------------


class TestFileExtractor:
    @pytest.fixture
    def temp_dir(self):
        dirpath = tempfile.mkdtemp()
        yield Path(dirpath)
        shutil.rmtree(dirpath)

    def create_gz_file(self, directory: Path, filename: str, content=b"test content") -> Path:
        file_path = directory / filename
        with gzip.open(file_path, "wb") as f:
            f.write(content)
        return file_path

    def create_tar_gz_file(self, directory: Path, filename: str, internal_files: dict) -> Path:
        tar_path = directory / filename
        with tarfile.open(tar_path, "w:gz") as tar:
            for name, data in internal_files.items():
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(data)
                tar.add(tmp.name, arcname=name)
                os.unlink(tmp.name)
        return tar_path

    def test_extract_gz_file(self, temp_dir):
        self.create_gz_file(temp_dir, "test.gz", b"hello world")
        FileExtractor().extract(temp_dir, show_progress=False)
        extracted_file = temp_dir / "test"
        assert extracted_file.exists()
        assert extracted_file.read_bytes() == b"hello world"

    def test_extract_tar_gz_file(self, temp_dir):
        self.create_tar_gz_file(temp_dir, "archive.tar.gz", {"file1.txt": b"data1", "file2.txt": b"data2"})
        FileExtractor().extract(temp_dir, show_progress=False)
        assert (temp_dir / "file1.txt").exists()
        assert (temp_dir / "file2.txt").exists()

    def test_remove_archive(self, temp_dir):
        gz_path = self.create_gz_file(temp_dir, "toremove.gz", b"remove me")
        FileExtractor().extract(temp_dir, show_progress=False, remove_archive=True)
        assert not gz_path.exists()

    def test_keep_archive(self, temp_dir):
        gz_path = self.create_gz_file(temp_dir, "tokeep.gz", b"keep me")
        FileExtractor().extract(temp_dir, show_progress=False, remove_archive=False)
        assert gz_path.exists()

    def test_ignore_non_matching_files(self, temp_dir):
        non_compressed = temp_dir / "not_a_gz.txt"
        non_compressed.write_text("just a text file")
        FileExtractor().extract(temp_dir, show_progress=False)
        assert non_compressed.exists()


# End-of-file (EOF)
