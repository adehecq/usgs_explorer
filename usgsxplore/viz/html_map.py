import html
from pathlib import Path

import folium
import geopandas as gpd

from usgsxplore.utils import as_gdf


def generate_html_map(source: str | Path | gpd.GeoDataFrame, output_file: str | Path = "scenes.html") -> None:
    """Save scene footprints as an interactive folium map, with the browse image in each popup when available.

    Raises ValueError if `source` is empty.
    """
    if Path(output_file).suffix.lower() != ".html":
        raise ValueError(f"Unsupported output format '{Path(output_file).suffix}', expected .html")

    gdf = as_gdf(source)
    if gdf.empty:
        raise ValueError("No scenes to map")

    centroids = gdf.to_crs(epsg=3857).centroid.to_crs(epsg=4326)
    center = centroids.y.mean(), centroids.x.mean()

    # OpenStreetMap's default tiles now reject folium/leaflet traffic under its
    # tile usage policy, so use Esri's freely embeddable satellite basemap instead.
    m = folium.Map(location=center, zoom_start=3, tiles="Esri.WorldImagery")
    first_col_name = gdf.columns[0]

    for _, row in gdf.iterrows():
        if row.geometry.geom_type == "Point":
            continue
        url = row.get("browse_url")
        # Missing values read back from a vector file may be NaN rather than None.
        popup = (
            folium.Popup(f'<img src="{html.escape(url)}" width="200px">', max_width=250)
            if isinstance(url, str)
            else None
        )
        folium.GeoJson(row.geometry, tooltip=f"{first_col_name}: {row[first_col_name]}", popup=popup).add_to(m)

    m.save(output_file)
