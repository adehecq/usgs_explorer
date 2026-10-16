import math
from pathlib import Path

import contextily as ctx
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from affine import Affine
from rasterio.enums import MergeAlg
from rasterio.features import rasterize
from rasterio.plot import plotting_extent
from rasterio.transform import from_origin

from usgsxplore.utils import RoiType, as_gdf


def generate_scenes_density(
    source: str | Path | gpd.GeoDataFrame,
    output_file: str | Path,
    roi: RoiType | None = None,
    resolution: float = 5000,
    date_column: str = "acquisition_date",
    overwrite: bool = False,
) -> None:
    """Plot the scene overlap density over a satellite basemap, with the ROI outline if provided, as a PNG or JPG.

    `resolution` is the pixel size in Web Mercator meters. If `date_column` exists in `source`, a histogram
    of acquisition dates is added below the map. The parent directory of `output_file`
    must already exist. Raises ValueError if `source` is empty.
    """
    output_file = Path(output_file)
    if output_file.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError(f"Unsupported output format '{output_file.suffix}', expected .png or .jpg")
    if not overwrite and output_file.exists():
        return

    gdf_3857 = as_gdf(source).to_crs(epsg=3857)
    if gdf_3857.empty:
        raise ValueError("No scenes to plot")

    density, transform = rasterize_density(gdf_3857, resolution)

    if date_column not in gdf_3857.columns:
        fig, ax = plt.subplots(figsize=(10, 10))
    else:
        fig, (ax, ax_time) = plt.subplots(2, 1, figsize=(10, 12), height_ratios=[5, 1])
        dates = pd.to_datetime(gdf_3857[date_column], errors="coerce").dropna()
        ax_time.hist(dates, bins=50, color="tab:blue")
        ax_time.set_title("Temporal coverage", fontsize=11)
        ax_time.set_ylabel("Scenes")
        ax_time.spines[["top", "right"]].set_visible(False)

    im = ax.imshow(
        np.ma.masked_equal(density, 0),
        cmap="viridis",
        alpha=0.7,
        extent=plotting_extent(density, transform),
        interpolation="nearest",
        zorder=1,
    )
    fig.colorbar(im, ax=ax, label="Overlapping scenes", shrink=0.6)
    if roi is not None:
        # Not `.boundary`: a point ROI has an empty boundary and would vanish.
        as_gdf(roi).to_crs(epsg=3857).plot(ax=ax, facecolor="none", edgecolor="red", linewidth=1.5, zorder=2)

    ctx.add_basemap(ax, zorder=0, source=ctx.providers.Esri.WorldImagery, attribution=False)
    ax.set_title(f"Scenes density ({len(gdf_3857)} scenes)", fontsize=13, fontweight="bold")
    ax.axis("off")
    fig.text(0.5, 0, "Basemap: Esri World Imagery", ha="center", va="top", fontsize=7, color="gray")

    fig.savefig(output_file, dpi=150, bbox_inches="tight")
    plt.close(fig)


def rasterize_density(gdf: gpd.GeoDataFrame, resolution: float) -> tuple[np.ndarray, Affine]:
    """Rasterize footprints into a uint16 overlap-count raster, in the CRS of `gdf`.

    `resolution` is the pixel size in units of that CRS. Returns the raster and its transform.
    """
    minx, miny, maxx, maxy = gdf.total_bounds
    # max(1, ...) keeps at least one pixel when the extent is zero (e.g. a single Point footprint).
    width = max(1, math.ceil((maxx - minx) / resolution))
    height = max(1, math.ceil((maxy - miny) / resolution))
    transform = from_origin(minx, maxy, resolution, resolution)

    density = rasterize(
        shapes=((geom, 1) for geom in gdf.geometry),
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype="uint16",
        merge_alg=MergeAlg.add,
    )
    return density, transform
