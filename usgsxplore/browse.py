from pathlib import Path

import numpy as np
import requests
import geopandas as gpd
from PIL import Image, UnidentifiedImageError
from io import BytesIO
from rasterio.transform import from_origin
from shapely.geometry import Polygon
from rasterio.warp import reproject, Resampling
import rasterio
from tqdm import tqdm


__all__ = ["download_browse_img", "mosaic_from_gdf"]

 #############################################################################################
#                           PUBLIC FUNCTIONS
#############################################################################################

def download_browse_img(url: str, grayscale: bool = True) -> np.ndarray:
    """
    Download an image from a URL and return it as a NumPy array.
    
    Args:
        url (str): URL of the image to download.
        grayscale (bool): If True, convert image to grayscale. Default is True.
        
    Returns:
        np.ndarray: Image data as a NumPy array.
        
    Raises:
        requests.HTTPError: If the HTTP request failed.
        ValueError: If the image cannot be opened or decoded.
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        raise requests.HTTPError(f"Failed to download image from {url}") from e

    try:
        with Image.open(BytesIO(response.content)) as img:
            if grayscale:
                img = img.convert("L")  # convert to grayscale
            arr = np.array(img)
    except UnidentifiedImageError as e:
        raise ValueError(f"Failed to decode image from {url}") from e

    return arr


def mosaic_from_gdf(
        gdf: gpd.GeoDataFrame, 
        output_path: str | Path, 
        url_key: str = "browse_url",
        resolution: int = 100,
        resampling: Resampling = Resampling.nearest,
        show_progress: bool = True) -> None:
    """
    Build a mosaic GeoTIFF from a GeoDataFrame of image footprints.

    Downloads images from URLs in the gdf, reprojects each on a final mosaic raster,
    and saves the result to `output_path`.

    Args:
        gdf: GeoDataFrame with image geometries and URLs.
        output_path: Path to save the final mosaic.
        url_key: Column name in gdf containing the image URLs.
        resampling: Rasterio resampling method (default: nearest).
        show_progress: If True, display a progress bar.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(exist_ok=True, parents=True)
    
    if (show_progress):
        p_bar = tqdm(desc=f"Mosaicing {output_path.name}", total=len(gdf))

    # 1. retrieve the first image in mem to know the pixel size
    first_img = download_browse_img(gdf.iloc[0][url_key])

    # 2. Compute the final size of the mosaic
    mosaic_width, mosaic_height, mosaic_transform = _compute_mosaic_size_and_transform(gdf, first_img)

    # 3. Create the mosaic raster
    with rasterio.open(output_path, "w", 
                       driver="GTiff",
                       width=mosaic_width,
                       height=mosaic_height,
                       count=1,
                       crs=str(gdf.crs),
                       dtype="uint8",
                       transform=mosaic_transform,
                       nodata=0,
                       compress= "lzw",) as dst:
        
        # 4. Loop around all row of the gdf to download all images 
        for idx, row in gdf.iterrows():
            # don't redownload the first img
            img = first_img if idx == 0 else download_browse_img(row[url_key])

            height, width = img.shape[:2]

            src_transform = _transform_from_polygon(row.geometry, width, height)

            # 5. Reproject the source image on the mosaic
            reproject(
                source=img,
                destination=rasterio.band(dst, 1),
                resampling=resampling,
                src_crs=str(gdf.crs),
                src_transform=src_transform,
                init_dest_nodata=False
            ) 
            if (show_progress):
                p_bar.update()
    
    if (show_progress):
        p_bar.close()


#############################################################################################
#                           PRIVATE FUNCTIONS
#############################################################################################


def _compute_mosaic_size_and_transform(gdf: gpd.GeoDataFrame, first_img: np.ndarray) -> tuple[int, int, rasterio.Affine]:
    """
    Compute mosaic dimensions and transform from a GeoDataFrame and first image.
    Returns: mosaic_width, mosaic_height, mosaic_transform
    """
    # taille pixel à partir de la première image
    height_src, width_src = first_img.shape[:2]

    # étendue totale du GDF
    minx, miny, maxx, maxy = gdf.union_all().bounds

    # résolution pixel
    pixel_width = (maxx - minx) / width_src
    pixel_height = (maxy - miny) / height_src

    # taille du mosaic
    mosaic_width = int(np.ceil((maxx - minx) / pixel_width))
    mosaic_height = int(np.ceil((maxy - miny) / pixel_height))

    # transform du mosaic
    mosaic_transform = from_origin(minx, maxy, pixel_width, pixel_height)

    return mosaic_width, mosaic_height, mosaic_transform

def _transform_from_polygon(polygon: Polygon, width: int, height: int) -> rasterio.Affine:
    """
    Compute the affine transform of a raster from its 4-corner polygon footprint.
    """
    ul, ur, lr, ll = np.array(polygon.exterior.coords[:4])

    # pixel vectors
    px = (ur - ul) / width
    py = (ll - ul) / height

    return rasterio.Affine(
        px[0], py[0], ul[0],
        px[1], py[1], ul[1],
    )