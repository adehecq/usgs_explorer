import geopandas as gpd
from matplotlib import pyplot as plt
import numpy as np
from shapely.geometry import box
import pandas as pd


import pandas as pd
import numpy as np
import geopandas as gpd

def compute_grid_metadata(
    gdf: gpd.GeoDataFrame,
    step: float = 1.0,
    date_column: str = "Acquisition Date"
) -> gpd.GeoDataFrame:
    """
    Compute acquisition-related metrics on a regular spatial grid.

    This function:
      - Filters polygon geometries
      - Converts the date column to datetime
      - Builds a regular grid covering the input geometries
      - Associates each grid cell with intersecting scenes
      - Aggregates acquisition dates per cell
      - Computes several metrics:
            * Number of intersecting images
            * Number of unique acquisition dates
            * Observation time span (years)
            * Peak acquisition year

    Parameters
    ----------
    gdf : geopandas.GeoDataFrame
        Input GeoDataFrame containing scene footprints and a date column.
    step : float, optional
        Cell size of the regular grid in CRS units (default is 1.0).
    date_column : str, optional
        Name of the acquisition date column (default is "Acquisition Date").

    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame representing the grid, enriched with acquisition metrics.

    Raises
    ------
    ValueError
        If the specified date column is not present in the input GeoDataFrame.
    """
    # 1. Check that the date column exists
    if date_column not in gdf.columns:
        raise ValueError(f"The GeoDataFrame must contain the date column: {date_column}")

    # 2. Filter only Polygons and MultiPolygons
    gdf_filtered = gdf.loc[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()

    # 3. Convert the date column to datetime
    gdf_filtered[date_column] = pd.to_datetime(gdf_filtered[date_column])

    # 4. Create a regular square grid covering the geometries
    grid_gdf = _create_regular_box_grid(gdf_filtered, step)

    # 5. Spatial join to associate grid cells with intersecting geometries
    joined = gpd.sjoin(grid_gdf, gdf_filtered, how="left", predicate="intersects")

    # 6. Collect all acquisition dates per grid cell
    dates_by_cell = joined.groupby(joined.index)[date_column].apply(lambda x: list(x.dropna().sort_values()))

    # --- Helper functions for metrics ---
    def time_span_years(dates):
        """Compute the time span in years for a list of dates."""
        if len(dates) <= 1:
            return 0
        return (dates[-1] - dates[0]).days / 365.25

    def peak_year(dates):
        """Return the most frequent acquisition year for a list of dates."""
        if len(dates) == 0:
            return np.nan
        years = [d.year for d in dates]
        return pd.Series(years).value_counts().idxmax()

    # 7. Compute metrics and store them in the grid GeoDataFrame
    grid_gdf["nb_images"] = dates_by_cell.apply(len).reindex(grid_gdf.index).fillna(0)
    grid_gdf["nb_unique_dates"] = dates_by_cell.apply(lambda dates: len(np.unique(dates))).reindex(grid_gdf.index).fillna(0)
    grid_gdf["time_span_years"] = dates_by_cell.apply(time_span_years).reindex(grid_gdf.index).fillna(0)
    grid_gdf["peak_year"] = dates_by_cell.apply(peak_year).reindex(grid_gdf.index).fillna(0)

    return grid_gdf


def generate_plots_from_grid(grid_gdf: gpd.GeoDataFrame) -> dict[str, plt.Figure]:
    """
    Generate a set of spatial analysis figures from a grid GeoDataFrame.

    This function produces one figure per acquisition metric:
        - Number of images per grid cell
        - Number of unique acquisition dates per grid cell
        - Observation time span in years
        - Peak acquisition year

    Each figure displays:
        - A world map background
        - The grid colored by the metric values
        - A colorbar and axis labels

    Parameters
    ----------
    grid_gdf : geopandas.GeoDataFrame
        GeoDataFrame representing the analysis grid, already enriched with metric columns.

    Returns
    -------
    dict[str, matplotlib.figure.Figure]
        Dictionary mapping metric names to their Matplotlib figures.
    """
    # 8. Generate plots for each metric
    figures = {
        "Number of Images": _plot_box_grid_on_world_map(
            grid_gdf, 
            "nb_images", 
            title="Number of Images per Grid Cell",
            vmax=np.percentile(grid_gdf["nb_images"], 99)
        ),
        "Number of Unique Dates": _plot_box_grid_on_world_map(
            grid_gdf, 
            "nb_unique_dates", 
            title="Number of Unique Acquisition Dates per Cell",
            vmax=np.percentile(grid_gdf["nb_unique_dates"], 99)
        ),
        "Observation Time Span": _plot_box_grid_on_world_map(
            grid_gdf, 
            "time_span_years", 
            title="Observation Time Span (Years)",
        ),
        "Peak Acquisition Year": _plot_box_grid_on_world_map(
            grid_gdf, 
            "peak_year", 
            title="Peak Acquisition Year"
        ),
    }

    return figures


def _create_regular_box_grid(gdf: gpd.GeoDataFrame, step: float = 1.0) -> gpd.GeoDataFrame:
    """
    Create a regular grid of square cells covering the extent of the input geometries.

    This function builds a regular grid of axis-aligned square polygons (cells) based on
    the bounding box of the union of all geometries in the input GeoDataFrame. Only the
    cells that intersect at least one geometry from the input are kept.

    Parameters
    ----------
    gdf : geopandas.GeoDataFrame
        Input GeoDataFrame containing polygon geometries. The CRS of this GeoDataFrame
        defines the coordinate system used for the grid.
    step : float, optional
        Size of each grid cell in CRS units (typically degrees or meters depending
        on the input CRS). Default is 1.0.

    Returns
    -------
    geopandas.GeoDataFrame
        A GeoDataFrame containing the generated grid cells as polygon geometries,
        with the same CRS as the input.

    Notes
    -----
    - The grid is aligned with the minimum x/y coordinates of the unioned extent.
    - Only cells that intersect the union of the input geometries are included.
    - This function assumes the input geometries are valid and represent planar polygons.
    """
    union_gdf = gdf.union_all("unary")
    minx, miny, maxx, maxy = union_gdf.bounds

    grid_cells = []
    x_coords = np.arange(minx, maxx, step)
    y_coords = np.arange(miny, maxy, step)

    for x in x_coords:
        for y in y_coords:
            cell = box(x, y, x + step, y + step)
            if union_gdf.intersects(cell):
                grid_cells.append(cell)

    return gpd.GeoDataFrame(geometry=grid_cells, crs=gdf.crs)


def _plot_box_grid_on_world_map(
    gdf: gpd.GeoDataFrame,
    column: str,
    title: str = "",
    vmin: float | None = None,
    vmax: float | None = None,
    url_world_map: str = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"
) -> plt.Figure:
    """
    Plot a GeoDataFrame grid on a world map with a colored variable.

    This function creates a map with:
      - Countries filled in white with black borders
      - Oceans in light blue
      - Grid cells colored according to a specified column
      - A vertical colorbar with proper labeling
      - A background grid in dashed lines
      - Axes labeled with longitude and latitude

    Parameters
    ----------
    gdf : geopandas.GeoDataFrame
        The GeoDataFrame containing the grid cells to plot.
    column : str
        The name of the column in gdf to use for coloring the grid cells.
    title : str, optional
        The title of the plot. Default is an empty string.
    vmin : float or None, optional
        Minimum value for the color scale. If None, the min of the column is used.
    vmax : float or None, optional
        Maximum value for the color scale. If None, the max of the column is used.
    url_world_map : str, optional
        URL or path to a GeoJSON file of country geometries. Default is Natural Earth low-res countries.

    Returns
    -------
    matplotlib.figure.Figure
        A Matplotlib Figure containing the plotted map.
    """

    # Create figure and axis
    fig, ax = plt.subplots(figsize=(10, 8))

    # Load world map GeoDataFrame
    world_map_gdf = gpd.read_file(url_world_map)

    # Set ocean color
    ax.set_facecolor("lightblue")

    # Plot countries in white with black borders
    world_map_gdf.plot(
        ax=ax,
        facecolor="white",   # fill color for countries
        edgecolor="black",   # border color
        linewidth=0.5,
        zorder=1
    )

    # Plot the grid cells colored by the specified column
    gdf.plot(
        ax=ax,
        column=column,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        edgecolor=None,
        legend=True,
        zorder=2,
        legend_kwds={
            "label": column,       # colorbar label
            "shrink": 0.7,         # fraction of figure height
            "pad": 0.02,           # space between figure and colorbar
            "orientation": "vertical"
        }
    )

    # Add dashed grid lines
    ax.grid(True, linestyle="--", color="gray", alpha=0.5)

    # Label axes with longitude and latitude
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    # Set plot title
    ax.set_title(title)

    # Adjust layout to avoid overlaps
    fig.tight_layout()

    return fig


