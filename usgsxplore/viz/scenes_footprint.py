from pathlib import Path

import contextily as ctx
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from usgsxplore.utils import RoiType, as_gdf, available_column


def generate_scenes_footprint(
    source: str | Path | gpd.GeoDataFrame,
    output_file: str | Path,
    roi: RoiType | None = None,
    overwrite: bool = False,
) -> None:
    """Plot scene footprints over a satellite basemap, with the ROI outline if provided, as a PNG or JPG.

    The parent directory of `output_file` must already exist. Raises ValueError if `source` is empty.
    """
    output_file = Path(output_file)
    if output_file.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError(f"Unsupported output format '{output_file.suffix}', expected .png or .jpg")
    if not overwrite and output_file.exists():
        return

    gdf_3857 = as_gdf(source).to_crs(epsg=3857)
    if gdf_3857.empty:
        raise ValueError("No scenes to plot")

    fig, ax = plt.subplots(figsize=(10, 10))
    n_available = plot_footprints(ax, gdf_3857, as_gdf(roi).to_crs(epsg=3857) if roi is not None else None)

    ctx.add_basemap(ax, zorder=0, source=ctx.providers.Esri.WorldImagery, attribution=False)
    ax.set_title(f"Scenes footprint ({n_available} available / {len(gdf_3857)} scenes)", fontsize=13, fontweight="bold")
    ax.axis("off")
    # Anchored to the map, not the figure: the map rarely fills the square figure and tight cropping stops at text.
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


def plot_footprints(ax, gdf_3857: gpd.GeoDataFrame, roi_3857: gpd.GeoDataFrame | None = None) -> int:
    """Draw scene footprints in green (available) or red (unavailable), the ROI outline in cyan, and a legend.

    Returns the number of available scenes.
    """
    # Unavailable first so available scenes are drawn on top where they overlap.
    available = available_column(gdf_3857).sort_values(kind="stable")
    gdf_3857 = gdf_3857.loc[available.index]
    colors = available.map({True: "green", False: "red"}).to_numpy()

    gdf_3857.plot(ax=ax, color=colors, alpha=0.2, zorder=1)
    gdf_3857.boundary.plot(ax=ax, color=colors, linewidth=0.5, zorder=2)
    if roi_3857 is not None:
        # Not `.boundary`: a point ROI has an empty boundary and would vanish.
        roi_3857.plot(ax=ax, facecolor="none", edgecolor="cyan", linewidth=1.5, zorder=3)

    ax.legend(
        handles=[
            Patch(facecolor="green", edgecolor="green", alpha=0.5, label="Available"),
            Patch(facecolor="red", edgecolor="red", alpha=0.5, label="Unavailable"),
        ],
        loc="upper right",
    )
    return int(available.sum())
