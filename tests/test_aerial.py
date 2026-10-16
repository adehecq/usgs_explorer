"""Aerial photos (aerial_combin): search and download."""

from pathlib import Path

import geopandas as gpd
import pytest

from usgsxplore import utils

# Small area near Phoenix, Arizona
BBOX = ["--bbox", "-111.87783", "32.66157", "-111.60280", "32.89378"]
ENTITY_ID = "AR5720008176242"


@pytest.fixture(scope="module")
def search_dir(invoke, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Search the single high-resolution photo acquired on 1972-11-21 over the test area."""
    out = tmp_path_factory.mktemp("aerial")
    invoke(
        "search", "aerial_combin", *BBOX, "-i", "1972-11-21", "1972-11-21", "-f", "HIGH_AVAILABLE=Y",
        "-o", str(out / "scenes.txt"), "-o", str(out / "scenes.gpkg"),
    )  # fmt: skip
    return out


def test_search(search_dir: Path) -> None:
    _, entity_ids = utils.read_textfile(str(search_dir / "scenes.txt"))
    assert entity_ids == [ENTITY_ID]
    assert list(gpd.read_file(search_dir / "scenes.gpkg")["entity_id"]) == [ENTITY_ID]


def test_columns(search_dir: Path, common_columns: set[str], caplog: pytest.LogCaptureFixture) -> None:
    gdf = gpd.read_file(search_dir / "scenes.gpkg")
    assert common_columns <= set(gdf.columns)
    utils.available_column(gdf)
    assert not caplog.records


def test_download(invoke, search_dir: Path, tmp_path: Path) -> None:
    # Product 0 is the medium resolution scan (~10 MB), much lighter than the high resolution one
    invoke("download", str(search_dir / "scenes.txt"), "-o", str(tmp_path), "-p", "0", "--hide-pbar")
    assert [p.name.split(".")[0] for p in tmp_path.iterdir()] == [ENTITY_ID]
