from __future__ import annotations

import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import contextily as ctx
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.plot import plotting_extent
from rasterio.vrt import WarpedVRT
from shapely.ops import unary_union
from tqdm import tqdm

from usgsxplore.core import download_browse_images
from usgsxplore.utils import get_strip_id_from_entity_id

WEB_MERCATOR_WORLD_EXTENT = 20037508.34


def generate_strip_figures(
    source: str | Path | gpd.GeoDataFrame,
    output_dir: str | Path,
    roi_source: str | Path | gpd.GeoDataFrame | None = None,
    max_workers: int = 4,
    overwrite: bool = False,
    highlight_unavailable: bool = True,
) -> None:
    """Generate one figure per strip in `source`, in parallel, under `output_dir`."""
    gdf = _as_gdf(source)
    roi_gdf = _as_gdf(roi_source) if roi_source is not None else None

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    gdf = gdf.assign(strip_id=gdf["entity_id"].map(get_strip_id_from_entity_id)).sort_values(["strip_id", "entity_id"])

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {}

        for strip_id, sub_gdf in gdf.groupby("strip_id"):
            output_file = output_dir / f"{strip_id}.jpg"

            # overwrite checking
            if not overwrite and output_file.exists():
                continue

            future = executor.submit(_generate_strip_figure, sub_gdf, output_file, roi_gdf, highlight_unavailable)
            futures[future] = strip_id

        if len(futures) == 0:
            return

        for future in tqdm(as_completed(futures), total=len(futures), desc="Strip figures"):
            strip_id = futures[future]
            try:
                future.result()
            except Exception as e:
                tqdm.write(f"[WARN] {strip_id}: {e}")


#############################################################################################
#                           HELPERS
#############################################################################################


def _generate_strip_figure(
    gdf: gpd.GeoDataFrame,
    output_file: str | Path,
    roi_gdf: gpd.GeoDataFrame | None = None,
    highlight_unavailable: bool = True,
) -> None:
    """Render a mosaic and ROI-context figure for a single strip.

    `gdf` must hold the scenes of a single strip and already have a `strip_id`
    column (see `get_strip_id_from_entity_id`). Downloaded browse images are
    cached in a per-strip working directory next to `output_file` and removed
    once the figure is saved. If `roi_gdf` is omitted, coverage is not computed
    and the context panel's basemap is zoomed out to the whole world instead
    of the ROI extent.
    """
    output_file = Path(output_file)
    strip_id = gdf["strip_id"].iloc[0]
    work_dir = output_file.parent / f"work_{strip_id}"

    try:
        download_browse_images(gdf, work_dir, max_workers=1, show_progress=False)

        fig, (ax_zoom, ax_ctx) = plt.subplots(2, 1, figsize=(8, 8))

        mosaic, transform = _build_mosaic(gdf, work_dir)

        ax_zoom.imshow(
            np.ma.masked_equal(mosaic[0], 0), cmap="gray", extent=plotting_extent(mosaic[0], transform), zorder=1
        )

        gdf_3857 = gdf.to_crs(epsg=3857)
        roi_3857 = roi_gdf.to_crs(epsg=3857) if roi_gdf is not None else None

        if highlight_unavailable:
            _highlight_unavailable_scenes(ax_zoom, gdf_3857)

        ctx.add_basemap(ax_zoom, zorder=0, source=ctx.providers.Esri.WorldImagery)
        ax_zoom.set_title("Mosaic view", fontsize=11)
        ax_zoom.axis("off")

        first_id = gdf.iloc[0].entity_id
        last_id = gdf.iloc[-1].entity_id
        coverage_line = f"Coverage: {_compute_coverage(gdf_3857, roi_3857):.1f}%  |  " if roi_3857 is not None else ""
        fig.suptitle(
            f"Strip {strip_id}\n{coverage_line}{first_id} → {last_id}",
            fontsize=13,
            fontweight="bold",
            y=1.01,
        )

        _plot_context(ax_ctx, gdf_3857, roi_3857)

        plt.tight_layout()
        plt.savefig(output_file, dpi=100, bbox_inches="tight")
        plt.close(fig)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _as_gdf(source: str | Path | gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Load a GeoDataFrame from a file path, or pass one through unchanged."""
    return source if isinstance(source, gpd.GeoDataFrame) else gpd.read_file(source)


def _build_mosaic(gdf: gpd.GeoDataFrame, input_browse_dir: Path):
    """Open browse GeoTIFFs, warp to EPSG:3857 and merge into a single mosaic."""
    srcs = []
    try:
        for row in gdf.itertuples():
            src = rasterio.open(input_browse_dir / f"{row.entity_id}.tif")
            srcs.append(WarpedVRT(src, crs="EPSG:3857"))
        return merge(srcs, res=200, nodata=0)
    finally:
        for vrt in srcs:
            vrt.close()


def _highlight_unavailable_scenes(ax, gdf_3857: gpd.GeoDataFrame):
    """Overlay red semi-transparent polygons on scenes where download_available is False."""
    if "download_available" not in gdf_3857.columns:
        return
    covered = None
    red_parts = []
    for row in gdf_3857.itertuples():
        geom = row.geometry
        visible = geom if covered is None else geom.difference(covered)
        if not row.download_available and not visible.is_empty:
            red_parts.append(visible)
        covered = geom if covered is None else covered.union(geom)
    if red_parts:
        gpd.GeoDataFrame(geometry=[unary_union(red_parts)], crs="EPSG:3857").plot(
            ax=ax, color="red", alpha=0.2, zorder=2
        )


def _compute_coverage(gdf_3857: gpd.GeoDataFrame, roi_3857: gpd.GeoDataFrame) -> float:
    """Return the percentage of the ROI area covered by the strip footprint."""
    roi_geom = roi_3857.union_all()
    strip_geom = gdf_3857.union_all()
    return strip_geom.intersection(roi_geom).area / roi_geom.area * 100


def _plot_context(ax, gdf_3857: gpd.GeoDataFrame, roi_3857: gpd.GeoDataFrame | None):
    """Plot the strip footprint overlaid on the ROI with a satellite basemap.

    When no ROI is given, the basemap is zoomed out to the whole world instead.
    """
    strip_union = gpd.GeoDataFrame(geometry=[gdf_3857.union_all()], crs="EPSG:3857")
    if roi_3857 is not None:
        roi_3857.boundary.plot(ax=ax, color="red", linewidth=1, zorder=1)
    strip_union.plot(ax=ax, color="yellow", alpha=0.4, zorder=2)
    strip_union.boundary.plot(ax=ax, color="yellow", linewidth=1.5, zorder=3)
    if roi_3857 is None:
        ax.set_xlim(-WEB_MERCATOR_WORLD_EXTENT, WEB_MERCATOR_WORLD_EXTENT)
        ax.set_ylim(-WEB_MERCATOR_WORLD_EXTENT, WEB_MERCATOR_WORLD_EXTENT)
    ctx.add_basemap(ax, zorder=0, source=ctx.providers.Esri.WorldImagery)
    ax.set_title("Footprint in ROI" if roi_3857 is not None else "Footprint (world view)", fontsize=11)
    ax.axis("off")


if __name__ == "__main__":
    generate_strip_figures("/home/godinlu/github/aspy/my-project/dataset/metadata/scenes_metadata.gpkg", ".")
