from pathlib import Path

import numpy as np
import requests
import geopandas as gpd
from PIL import Image, UnidentifiedImageError
from io import BytesIO
from rasterio.transform import from_origin, from_bounds
from shapely.geometry import Polygon
from rasterio.warp import reproject, Resampling
import rasterio
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed


__all__ = ["generate_strips_from_browse", "download_browse_img", "mosaic_from_gdf"]

#############################################################################################
#                           PUBLIC FUNCTIONS
#############################################################################################


def generate_strips_from_browse(
    gdf: gpd.GeoDataFrame,
    output_dir: str | Path = "",
    strip_id_key: str = "strip_id",
    url_key: str = "browse_url",
    resolution: int = 100,
    resampling: Resampling = Resampling.nearest,
    max_workers: int = 4,
    overwrite: bool = False,
    show_progress: bool = True,
) -> None:
    """
    Generate mosaics (GeoTIFF) for each strip in a GeoDataFrame of image footprints.

    For each unique strip in `gdf` (grouped by `strip_id_key`), this function:
        1. Skips the strip if the output file already exists (unless `overwrite=True`)
        2. Downloads images from URLs in the group
        3. Reprojects and mosaics the images into a single raster
        4. Saves the raster to `output_dir/<strip_id>.tif`

    Parameters
    ----------
    gdf : geopandas.GeoDataFrame
        GeoDataFrame containing footprints and URLs of images.
    output_dir : str or Path
        Directory where mosaics will be saved.
    strip_id_key : str, default "strip_id"
        Column name in `gdf` defining strips.
    url_key : str, default "browse_url"
        Column name in `gdf` containing image URLs.
    resolution : int, default 100
        Pixel size for the mosaic in the CRS units.
    resampling : rasterio.enums.Resampling, default Resampling.nearest
        Resampling method for reprojecting images.
    max_workers : int, default 4
        Number of threads to use for parallel mosaic generation.
    overwrite : bool, default False
        If True, existing mosaics will be overwritten.
    show_progress : bool, default True
        If True, display a progress bar for mosaics.

    Returns
    -------
    None
    """
    output_dir = Path(output_dir)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        # 1. add all tasks to the executor
        for strip_id, group in gdf.groupby(strip_id_key):
            output_path = output_dir / f"{strip_id}.tif"

            # skip existing files if not overwrite
            if (output_path.exists() and not overwrite): 
                continue

            # add the task to the executor
            futures.append(
                executor.submit(
                    mosaic_from_gdf,
                    group,
                    output_path,
                    url_key=url_key,
                    resolution=resolution,
                    resampling=resampling,
                    show_progress=False,
                )
            )

        # 2 .wait for all task to complete and add a pbar if show_progress
        if (show_progress):
            with tqdm(total=len(futures)) as pbar:
                for fut in as_completed(futures):
                    try:
                        fut.result()
                    except Exception as e:
                        print(f"Error in a strip: {e}")
                    pbar.update(1)
        else:
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    print(f"Error in a strip: {e}")



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
    show_progress: bool = True,
) -> None:
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

    if show_progress:
        p_bar = tqdm(desc=f"Mosaicing {output_path.name}", total=len(gdf))

    # 1. reproject the gdf on a local utm
    utm_crs = gdf.estimate_utm_crs()
    gdf_utm = gdf.to_crs(utm_crs)

    # 2. get the boundary of the gdf
    minx, miny, maxx, maxy = gdf_utm.total_bounds

    # 3. compute the mosaic width and size
    mosaic_width = int(np.ceil((maxx - minx) / resolution))
    mosaic_height = int(np.ceil((maxy - miny) / resolution))

    mosaic_transform = from_origin(minx, maxy, resolution, resolution)

    # 3. Create the mosaic raster
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        width=mosaic_width,
        height=mosaic_height,
        count=1,
        crs=utm_crs,
        dtype="uint8",
        transform=mosaic_transform,
        nodata=0,
        compress="jpeg",
        quality=75,
    ) as dst:
        # 4. Loop around all row of the gdf to download all images
        for idx, row in gdf_utm.iterrows():
            img = download_browse_img(row[url_key])

            height, width = img.shape[:2]

            src_transform = _transform_from_polygon(
                row.geometry, width=width, height=height
            )

            # 5. Reproject the source image on the mosaic
            reproject(
                source=img,
                destination=rasterio.band(dst, 1),
                resampling=resampling,
                src_crs=utm_crs,
                src_transform=src_transform,
                init_dest_nodata=False,
            )
            if show_progress:
                p_bar.update()

    if show_progress:
        p_bar.close()


#############################################################################################
#                           PRIVATE FUNCTIONS
#############################################################################################


def _compute_mosaic_size_and_transform(
    gdf: gpd.GeoDataFrame, first_img: np.ndarray
) -> tuple[int, int, rasterio.Affine]:
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


def _transform_from_polygon(
    polygon: Polygon, width: int, height: int
) -> rasterio.Affine:
    """
    Compute the affine transform of a raster from its 4-corner polygon footprint.

    Assumes that the polygon has **exactly 4 vertices** in the following stable order:
        lower-left (LL), lower-right (LR), upper-right (UR), upper-left (UL)
    """

    coords = np.array(polygon.exterior.coords[:4])
    if len(coords) < 4:
        raise ValueError(f"Polygon has fewer than 4 points: {len(coords)}")
    ll, lr, ur, ul = np.array(polygon.exterior.coords[:4])

    # pixel vectors
    px = (ur - ul) / width
    py = (ll - ul) / height

    return rasterio.Affine(
        px[0],
        py[0],
        ul[0],
        px[1],
        py[1],
        ul[1],
    )
