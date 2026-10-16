"""KH-9 Mapping Camera (declassii): search, download-browse and viz strip."""

from pathlib import Path

import geopandas as gpd
import pytest
import rasterio

from usgsxplore import utils

# Small area near Phoenix, Arizona
BBOX = ["--bbox", "-111.87783", "32.66157", "-111.60280", "32.89378"]
ENTITY_IDS = ["DZB1212-500245L005001", "DZB1212-500245L006001", "DZB1212-500245L007001"]


@pytest.fixture(scope="module")
def search_dir(invoke, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Search the single strip acquired on 1976-08-28 over the test area."""
    out = tmp_path_factory.mktemp("kh9mc")
    invoke(
        "search", "declassii", *BBOX, "-i", "1976-08-28", "1976-08-28", "-f", "camera=L",
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


def test_download_browse(invoke, search_dir: Path, tmp_path: Path) -> None:
    invoke("download-browse", str(search_dir / "scenes.gpkg"), "-o", str(tmp_path), "--hide-pbar")
    assert sorted(p.stem for p in tmp_path.glob("*.tif")) == ENTITY_IDS
    with rasterio.open(tmp_path / f"{ENTITY_IDS[0]}.tif") as src:
        gcps, crs = src.gcps
        assert len(gcps) == 4
        assert crs is not None


def test_download_browse_jpg(invoke, search_dir: Path, tmp_path: Path) -> None:
    invoke("download-browse", str(search_dir / "scenes.gpkg"), "-o", str(tmp_path), "-f", "jpg", "--hide-pbar")
    assert sorted(p.stem for p in tmp_path.glob("*.jpg")) == ENTITY_IDS


def test_strip_viz(invoke, search_dir: Path, tmp_path: Path) -> None:
    invoke("viz", "strip", str(search_dir / "scenes.gpkg"), "-o", str(tmp_path))
    assert [p.name for p in tmp_path.glob("*.jpg")] == ["DZB1212-500245L.jpg"]
