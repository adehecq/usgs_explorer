import math
from pathlib import Path

import contextily as ctx
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from affine import Affine
from mpl_toolkits.axes_grid1 import make_axes_locatable
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

    fig, ax = plt.subplots(figsize=(10, 10))
    im = ax.imshow(
        np.ma.masked_equal(density, 0),
        cmap="viridis",
        alpha=0.7,
        extent=plotting_extent(density, transform),
        interpolation="nearest",
        zorder=1,
    )
    # The equal-aspect map rarely fills its axes; a divider attaches the side panels to the drawn map,
    # so they match its size and leave no gap.
    divider = make_axes_locatable(ax)
    fig.colorbar(im, cax=divider.append_axes("right", size=0.25, pad=0.15), label="Overlapping scenes")

    if date_column in gdf_3857.columns:
        ax_time = divider.append_axes("bottom", size=1.8, pad=0.6)
        dates = pd.to_datetime(gdf_3857[date_column], errors="coerce").dropna()
        ax_time.hist(dates, bins=50, color="tab:blue")
        ax_time.set_title("Temporal coverage", fontsize=11)
        ax_time.set_ylabel("Scenes")
        ax_time.spines[["top", "right"]].set_visible(False)
    if roi is not None:
        # Not `.boundary`: a point ROI has an empty boundary and would vanish.
        as_gdf(roi).to_crs(epsg=3857).plot(ax=ax, facecolor="none", edgecolor="red", linewidth=1.5, zorder=2)

    ctx.add_basemap(ax, zorder=0, source=ctx.providers.Esri.WorldImagery, attribution=False)
    ax.set_title(f"Scenes density ({len(gdf_3857)} scenes)", fontsize=13, fontweight="bold")
    ax.axis("off")
    ax.text(
        0.5,
        -0.01,
        "Basemap: Esri World Imagery",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=7,
        color="gray",
    )

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
