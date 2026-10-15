from pathlib import Path

import contextily as ctx
import geopandas as gpd
import matplotlib.pyplot as plt

from usgsxplore.utils import as_gdf


def generate_scenes_footprint(
    source: str | Path | gpd.GeoDataFrame,
    output_file: str | Path,
    roi_source: str | Path | gpd.GeoDataFrame | None = None,
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
    gdf_3857.plot(ax=ax, color="yellow", alpha=0.2, zorder=1)
    gdf_3857.boundary.plot(ax=ax, color="yellow", linewidth=0.5, zorder=2)
    if roi_source is not None:
        # Not `.boundary`: a point ROI has an empty boundary and would vanish.
        as_gdf(roi_source).to_crs(epsg=3857).plot(ax=ax, facecolor="none", edgecolor="red", linewidth=1.5, zorder=3)

    ctx.add_basemap(ax, zorder=0, source=ctx.providers.Esri.WorldImagery, attribution=False)
    ax.set_title(f"Scenes footprint ({len(gdf_3857)} scenes)", fontsize=13, fontweight="bold")
    ax.axis("off")
    fig.text(0.5, 0, "Basemap: Esri World Imagery", ha="center", va="top", fontsize=7, color="gray")

    fig.savefig(output_file, dpi=150, bbox_inches="tight")
    plt.close(fig)
