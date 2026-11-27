import logging
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import requests
from PIL import Image
from pyproj import Geod
from rasterio.control import GroundControlPoint
from rasterio.errors import NotGeoreferencedWarning
from rasterio.transform import GCPTransformer, from_origin
from rasterio.warp import Resampling, reproject
from tqdm import tqdm

from usgsxplore.utils import as_gdf

__all__ = ["download_browse_images"]

CRS = "EPSG:4326"
METERS_PER_DEGREE = 111_320

# rasterio also forwards transformer options to the warper, which logs a spurious warning for each of them.
logging.getLogger("rasterio._env").addFilter(lambda record: "SRC_METHOD" not in record.getMessage())
# The in-memory source of the warp is georeferenced by GCPs, which rasterio applies after raising this.
warnings.filterwarnings("ignore", category=NotGeoreferencedWarning, module="rasterio.warp")


def download_browse_images(
    source: str | Path | gpd.GeoDataFrame,
    output_dir: str | Path,
    max_workers: int = 4,
    overwrite: bool = False,
    show_progress: bool = True,
) -> list[Path]:
    """Download the browse image of each scene as a north-up GeoTIFF named `<entity_id>.tif`.

    :param source: vector file or GeoDataFrame with `entity_id`, `browse_url` and `*_corner_*_dec` columns
    :param output_dir: directory where the GeoTIFFs are saved
    :param max_workers: number of parallel download threads
    :param overwrite: if True, download again the images that already exist
    :param show_progress: if True, display a progress bar
    :return: paths of the available images in `source` order, without the failed scenes
    """
    gdf = as_gdf(source)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = [output_dir / f"{entity_id}.tif" for entity_id in gdf["entity_id"]]
    failed = set()
    with requests.Session() as session, ThreadPoolExecutor(max_workers) as executor:
        futures = {
            executor.submit(_download_scene, row, path, session): path
            for row, path in zip(gdf.to_dict("records"), paths)
            if overwrite or not path.exists()
        }
        for future in tqdm(
            as_completed(futures), total=len(futures), desc="Downloading browse images", disable=not show_progress
        ):
            try:
                future.result()
            except Exception as e:
                failed.add(futures[future])
                tqdm.write(f"[WARN] {futures[future].stem}: {e}")

    return [path for path in paths if path not in failed]


def _download_scene(row: dict, output_file: Path, session: requests.Session) -> None:
    """Fetch the browse image of one scene in grayscale and save it as a warped GeoTIFF."""
    response = session.get(row["browse_url"], timeout=10)
    response.raise_for_status()
    with Image.open(BytesIO(response.content)) as jpg:
        img = np.array(jpg.convert("L"))

    corners = ("nw", "ne", "se", "sw")
    lons = np.array([row[f"{c}_corner_long_dec"] for c in corners], dtype=float)
    lats = np.array([row[f"{c}_corner_lat_dec"] for c in corners], dtype=float)
    # A scene crossing the antimeridian would otherwise span the whole globe.
    if np.ptp(lons) > 180:
        lons[lons < 0] += 360

    height, width = img.shape
    pixels = [(0, 0), (0, width), (height, width), (height, 0)]
    gcps = [GroundControlPoint(r, c, x, y) for (r, c), x, y in zip(pixels, lons, lats)]
    _save_warped_tif(img, gcps, output_file)


def _output_grid(gcps: list[GroundControlPoint], width: int, height: int):
    """Return the transform and (height, width) shape of the north-up grid covering the warped image.

    `gcps` are the four image corners, in clockwise order from the top-left one.
    """
    lons, lats = [g.x for g in gcps], [g.y for g in gcps]
    # Edge lengths in meters, in the order top, right, bottom, left.
    edges = Geod(ellps="WGS84").line_lengths([*lons, lons[0]], [*lats, lats[0]])
    # The finest of the four edge resolutions, so that no detail is lost.
    pixel_size = min(length / count for length, count in zip(edges, (width, height, width, height)))
    yres = pixel_size / METERS_PER_DEGREE
    xres = yres / np.cos(np.radians(np.mean(lats)))

    # The spline can bend the image edges beyond the bounds of the corners.
    cols, rows = np.linspace(0, width, 50), np.linspace(0, height, 50)
    outline_cols = np.concatenate([cols, cols, np.zeros(50), np.full(50, width)])
    outline_rows = np.concatenate([np.zeros(50), np.full(50, height), rows, rows])
    with GCPTransformer(gcps, tps=True) as transformer:
        xs, ys = transformer.xy(outline_rows, outline_cols, offset="ul")

    west, north = min(xs), max(ys)
    shape = int(np.ceil((north - min(ys)) / yres)), int(np.ceil((max(xs) - west) / xres))
    return from_origin(west, north, xres, yres), shape


def _save_warped_tif(img: np.ndarray, gcps: list[GroundControlPoint], output_file: Path) -> None:
    """Warp a grayscale image with a thin plate spline and write it as a GeoTIFF with 0 as nodata."""
    transform, shape = _output_grid(gcps, img.shape[1], img.shape[0])
    warped = np.zeros(shape, dtype=img.dtype)
    reproject(
        np.maximum(img, 1),  # 0 is reserved for nodata
        warped,
        gcps=gcps,
        src_crs=CRS,
        dst_crs=CRS,
        dst_transform=transform,
        dst_nodata=0,
        resampling=Resampling.bilinear,
        SRC_METHOD="GCP_TPS",
    )

    # Existing files are not downloaded again, so an interrupted write must not leave one behind.
    tmp_file = output_file.with_suffix(".tmp")
    with rasterio.open(
        tmp_file,
        "w",
        driver="GTiff",
        height=shape[0],
        width=shape[1],
        count=1,
        dtype=warped.dtype,
        crs=CRS,
        transform=transform,
        nodata=0,
        compress="deflate",
    ) as dst:
        dst.write(warped, 1)
    tmp_file.replace(output_file)
