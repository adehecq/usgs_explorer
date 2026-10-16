"""KH-9 Panoramic Camera (declassiii): search and viz strip."""

from pathlib import Path

import geopandas as gpd
import pytest

from usgsxplore import utils

# Small area near Phoenix, Arizona
BBOX = ["--bbox", "-111.87783", "32.66157", "-111.60280", "32.89378"]
ENTITY_IDS = ["D3C1211-400739F001", "D3C1211-400739F002", "D3C1211-400739F003"]


@pytest.fixture(scope="module")
def search_dir(invoke, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Search the single forward-camera strip acquired on 1976-03-17 over the test area."""
    out = tmp_path_factory.mktemp("kh9pc")
    invoke(
        "search", "declassiii", *BBOX, "-i", "1976-03-17", "1976-03-17",
        "-o", str(out / "scenes.txt"), "-o", str(out / "scenes.gpkg"),
    )  # fmt: skip
    return out


def test_search(search_dir: Path) -> None:
    _, entity_ids = utils.read_textfile(str(search_dir / "scenes.txt"))
    assert sorted(entity_ids) == ENTITY_IDS
    assert sorted(gpd.read_file(search_dir / "scenes.gpkg")["entity_id"]) == ENTITY_IDS


def test_columns(search_dir: Path, common_columns: set[str], caplog: pytest.LogCaptureFixture) -> None:
    gdf = gpd.read_file(search_dir / "scenes.gpkg")
    assert common_columns <= set(gdf.columns)
    utils.available_column(gdf)
    assert not caplog.records


def test_strip_viz(invoke, search_dir: Path, tmp_path: Path) -> None:
    invoke("viz", "strip", str(search_dir / "scenes.gpkg"), "-o", str(tmp_path))
    assert [p.name for p in tmp_path.glob("*.jpg")] == ["D3C1211-400739F.jpg"]
