import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import contextily as ctx
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.merge import merge
from rasterio.plot import plotting_extent
from rasterio.vrt import WarpedVRT
from tqdm import tqdm

from usgsxplore.core import download_browse_images
from usgsxplore.utils import RoiType, as_gdf, get_strip_id_from_entity_id
from usgsxplore.viz.scenes_footprint import plot_footprints

WEB_MERCATOR_WORLD_EXTENT = 20037508.34
# Half-width of the ROI-less context view, as a multiple of the strip's largest dimension.
CONTEXT_ZOOM_FACTOR = 3


def build_strip_mosaics(
    source: str | Path | gpd.GeoDataFrame,
    output_dir: str | Path,
    max_workers: int = 4,
    overwrite: bool = False,
    show_progress: bool = True,
) -> list[Path]:
    """Download the browse images of `source`, then write one mosaic per strip and the footprint layer.

    :param source: vector file or GeoDataFrame of scenes, as expected by `download_browse_images`
    :param output_dir: directory receiving `scenes/`, `mosaics/` and `footprints.gpkg`
    :param max_workers: number of parallel download threads
    :param overwrite: if True, download again the scenes that already exist
    :param show_progress: if True, display a download progress bar
    :return: paths of the strip mosaics
    """
    gdf = as_gdf(source)
    output_dir = Path(output_dir)
    mosaic_dir = output_dir / "mosaics"
    mosaic_dir.mkdir(parents=True, exist_ok=True)

    scene_files = download_browse_images(gdf, output_dir / "scenes", max_workers, overwrite, show_progress)
    scenes = {path.stem: path for path in scene_files}

    gdf = gdf.assign(
        strip_id=gdf["entity_id"].map(get_strip_id_from_entity_id),
        scene_path=gdf["entity_id"].map(lambda i: f"scenes/{i}.tif" if i in scenes else None),
    )
    gdf.to_file(output_dir / "footprints.gpkg", driver="GPKG")

    mosaic_files = []
    for strip_id, strip in gdf.sort_values("entity_id").groupby("strip_id"):
        mosaic_file = mosaic_dir / f"{strip_id}.tif"
        if files := [scenes[i] for i in strip["entity_id"] if i in scenes]:
            _write_mosaic(files, mosaic_file)
            mosaic_files.append(mosaic_file)
        else:
            mosaic_file.unlink(missing_ok=True)

    return mosaic_files


def generate_strip_figures(
    source: str | Path | gpd.GeoDataFrame,
    output_dir: str | Path,
    roi: RoiType | None = None,
    max_workers: int = 4,
    overwrite: bool = False,
) -> None:
    """Build the strip mosaics of `source`, then save one `figures/<strip_id>.jpg` per strip.

    Each figure shows the strip mosaic next to a context map of the scene footprints colored by
    availability. Strips that fail are reported as warnings without stopping the others.

    :param source: vector file or GeoDataFrame of scenes, as expected by `download_browse_images`
    :param output_dir: directory receiving `figures/` and the outputs of `build_strip_mosaics`
    :param roi: region of interest drawn on the context map and used to compute the coverage
    :param max_workers: number of parallel download threads, then of figure rendering processes
    :param overwrite: if True, render again the figures that already exist
    """
    roi_gdf = as_gdf(roi) if roi is not None else None
    output_dir = Path(output_dir)
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)

    mosaic_files = build_strip_mosaics(source, output_dir, max_workers=max_workers)
    pending = [file for file in mosaic_files if overwrite or not (figure_dir / f"{file.stem}.jpg").exists()]
    if not pending:
        return

    gdf = gpd.read_file(output_dir / "footprints.gpkg").sort_values("entity_id")

    # fork() in a multi-threaded parent (requests, tqdm) can deadlock the workers
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=multiprocessing.get_context("spawn")) as executor:
        futures = {
            executor.submit(
                _generate_strip_figure,
                gdf[gdf["strip_id"] == file.stem],
                file,
                figure_dir / f"{file.stem}.jpg",
                roi_gdf,
            ): file.stem
            for file in pending
        }

        for future in tqdm(as_completed(futures), total=len(futures), desc="Strip figures"):
            strip_id = futures[future]
            try:
                future.result()
            except Exception as e:
                tqdm.write(f"[WARN] {strip_id}: {e}")


def _write_mosaic(scene_files: list[Path], mosaic_file: Path) -> None:
    """Merge scenes into a GeoTIFF at their finest resolution, later scenes on top."""
    resolutions = []
    for file in scene_files:
        with rasterio.open(file) as src:
            resolutions.append(src.res)

    merge(
        scene_files,
        res=tuple(np.min(resolutions, axis=0)),
        method="last",
        dst_path=mosaic_file,
        # The block size inherited from the striped scenes is only valid for a tiled file.
        dst_kwds={"compress": "deflate", "tiled": True, "blockxsize": 256, "blockysize": 256},
    )


def _generate_strip_figure(
    gdf: gpd.GeoDataFrame, mosaic_file: Path, output_file: Path, roi_gdf: gpd.GeoDataFrame | None = None
) -> None:
    """Render the mosaic and context map figure of a single strip.

    `gdf` holds the footprint layer rows of the strip, sorted by `entity_id`. Without `roi_gdf`, coverage
    is not computed and the context map shows a region centered on the strip instead of the ROI extent.
    """
    fig, (ax_zoom, ax_ctx) = plt.subplots(1, 2, figsize=(11, 6))

    with rasterio.open(mosaic_file) as src, WarpedVRT(src, crs="EPSG:3857") as warped:
        ax_zoom.imshow(warped.read(1, masked=True), cmap="gray", extent=plotting_extent(warped), zorder=1)

    gdf_3857 = gdf.to_crs(epsg=3857)
    roi_3857 = roi_gdf.to_crs(epsg=3857) if roi_gdf is not None else None

    _fill_square_panel(ax_zoom)
    ctx.add_basemap(ax_zoom, zorder=0, source=ctx.providers.Esri.WorldImagery, attribution=False)
    ax_zoom.set_title("Mosaic view", fontsize=11)
    ax_zoom.axis("off")

    first_id = gdf.iloc[0].entity_id
    last_id = gdf.iloc[-1].entity_id
    date = pd.to_datetime(gdf["acquisition_date"]).min().date()
    details = []
    if roi_3857 is not None:
        details.append(f"Coverage: {_compute_coverage(gdf_3857, roi_3857):.1f}%")
    if missing := gdf["scene_path"].isna().sum():
        details.append(f"Missing images: {missing}/{len(gdf)}")
    details.append(f"{first_id} → {last_id}")
    fig.suptitle(f"Strip {mosaic_file.stem} ({date})\n{'  |  '.join(details)}", fontsize=13, fontweight="bold", y=1.01)

    _plot_context(ax_ctx, gdf_3857, roi_3857)
    fig.text(0.5, 0, "Basemap: Esri World Imagery", ha="center", va="top", fontsize=7, color="gray")

    plt.tight_layout()
    plt.savefig(output_file, dpi=100, bbox_inches="tight")
    plt.close(fig)


def _fill_square_panel(ax):
    """Widen the data limits so the map fills a square panel instead of shrinking to its extent."""
    ax.set(aspect="equal", adjustable="datalim", box_aspect=1)
    # Limits are only adjusted at draw time, but the basemap is fetched for the current ones.
    ax.apply_aspect()


def _compute_coverage(gdf_3857: gpd.GeoDataFrame, roi_3857: gpd.GeoDataFrame) -> float:
    """Return the percentage of the ROI area covered by the strip footprint."""
    roi_geom = roi_3857.union_all()
    strip_geom = gdf_3857.union_all()
    return strip_geom.intersection(roi_geom).area / roi_geom.area * 100


def _plot_context(ax, gdf_3857: gpd.GeoDataFrame, roi_3857: gpd.GeoDataFrame | None):
    """Plot the strip footprint overlaid on the ROI with a satellite basemap.

    When no ROI is given, the view is a square region centered on the strip instead.
    """
    plot_footprints(ax, gdf_3857, roi_3857)
    if roi_3857 is None:
        minx, miny, maxx, maxy = gdf_3857.total_bounds
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        half = CONTEXT_ZOOM_FACTOR * max(maxx - minx, maxy - miny)
        # Tiles do not exist beyond the Web Mercator bounds, which high-latitude strips would exceed.
        cy = np.clip(cy, half - WEB_MERCATOR_WORLD_EXTENT, WEB_MERCATOR_WORLD_EXTENT - half)
        ax.set_xlim(cx - half, cx + half)
        ax.set_ylim(cy - half, cy + half)
    _fill_square_panel(ax)
    ctx.add_basemap(ax, zorder=0, source=ctx.providers.Esri.WorldImagery, attribution=False)
    ax.set_title("Footprint in ROI" if roi_3857 is not None else "Footprint (regional view)", fontsize=11)
    ax.axis("off")
