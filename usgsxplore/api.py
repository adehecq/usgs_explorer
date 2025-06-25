"""
Description: module contain the API class to download and interact with the USGS api
(https://m2m.cr.usgs.gov/api/docs/json/).
This class is highly inspired by https://github.com/yannforget/landsatxplore.

Last modified: 2024
Author: Luc Godin
"""

import datetime
import json
import os
import random
import string
import time
from collections.abc import Generator
from urllib.parse import urljoin

import requests
from tqdm import tqdm

import usgsxplore.errors as err
from usgsxplore.filter import SceneFilter
from usgsxplore.utils import (
    download_scenes,
    extract_files_in_place,
    process_download_options,
)

API_URL = "https://m2m.cr.usgs.gov/api/api/json/stable/"


class API:
    """EarthExplorer API."""

    def __init__(self, username: str, token: str, debug_mode: bool = False) -> None:
        """EarthExplorer API.

        :param username: EarthExplorer username.
        :param token: EarthExplorer token.
        """
        self.url = API_URL
        self.session = requests.Session()
        self.label = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.debug_mode = debug_mode
        self.login(username, token)

    @staticmethod
    def raise_api_error(response: requests.Response) -> None:
        """Parse API response and return the appropriate exception.

        :param response: Response from USGS API.
        :raise USGSAuthenticationError: If credentials are not valid of if user lacks permission.
        :raise USGSRateLimitError: If there are too many request
        :raise USGSError: If the USGS API returns a non-null error code.
        """
        data = response.json()
        error_code = data.get("errorCode")
        error_msg = data.get("errorMessage")
        if error_code:
            if error_code in ("AUTH_INVALID", "AUTH_UNAUTHROIZED", "AUTH_KEY_INVALID"):
                raise err.USGSAuthenticationError(f"{error_code}: {error_msg}.")
            if error_code == "RATE_LIMIT":
                raise err.USGSRateLimitError(f"{error_code}: {error_msg}.")
            if error_code == "DATASET_INVALID":
                raise err.USGSInvalidDataset(f"{error_code}: {error_msg}.")
            raise err.USGSError(f"{error_code}: {error_msg}.")

    def request(
        self, endpoint: str, params: dict = None, retries: int = 1, timeout: int = 40
    ) -> dict:
        """
        Perform a request to the USGS M2M API with a timeout and retry mechanism.

        :param endpoint: API endpoint.
        :param params: API parameters.
        :param retries: Number of retries in case of rate limit error.
        :raise USGSAuthenticationError: If credentials are not valid or if user lacks permission.
        :raise USGSRateLimitError: If there are too many requests.
        :return: JSON data returned by the USGS API.
        """
        url = urljoin(self.url, endpoint)
        data = json.dumps(params)

        for attempt in range(retries + 1):
            try:
                if self.debug_mode:
                    print(f"[DEBUG] Request attempt {attempt + 1}/{retries + 1}")
                    print(f"[DEBUG] URL: {url}")
                    print(f"[DEBUG] Params: {params}")
                    print(f"[DEBUG] Timeout: {timeout}")

                response = self.session.get(url, data=data, timeout=timeout)

                if self.debug_mode:
                    print(f"[DEBUG] Response status code: {response.status_code}")
                    print(f"[DEBUG] Response text: {response.text}")

                self.raise_api_error(response)
                return response.json().get("data")
            except err.USGSRateLimitError:
                if attempt < retries:
                    if self.debug_mode:
                        print("[DEBUG] Rate limit hit, retrying in 3s...")
                    time.sleep(3)  # Attente avant de réessayer
                else:
                    raise
            except requests.Timeout:
                if attempt < retries:
                    if self.debug_mode:
                        print("[DEBUG] Request timed out, retrying in 2s...")
                    time.sleep(2)  # Attente avant de réessayer en cas de timeout
                else:
                    raise requests.Timeout("Request timed out after multiple attempts")

    def login(self, username: str, token: str) -> None:
        """Get an API key. With the login-token request

        :param username: EarthExplorer username.
        :param token: EarthExplorer token.
        :raise USGSAuthenticationError: If the authentication failed
        """
        login_url = urljoin(self.url, "login-token")
        payload = {"username": username, "token": token}
        r = self.session.post(login_url, json.dumps(payload))
        self.raise_api_error(r)
        self.session.headers["X-Auth-Token"] = r.json().get("data")

    def logout(self) -> None:
        """Logout from USGS M2M API."""
        self.request("logout")
        self.session = requests.Session()

    def get_entity_id(
        self, display_id: str | list[str], dataset: str
    ) -> str | list[str]:
        """Get scene ID from product ID.

        Note
        ----
        As the lookup endpoint has been removed in API v1.5, the function makes
        successive calls to scene-list-add and scene-list-get in order to retrieve
        the scene IDs. A temporary sceneList is created and removed at the end of the
        process.

        :param display_id: Input display ID. Can also be a list of display IDs.
        :param dataset: Dataset alias.
        :return: Output entity ID. Can also be a list of entity IDs depending on input.
        """
        # scene-list-add support both entityId and entityIds input parameters
        param = "entityId"
        if isinstance(display_id, list):
            param = "entityIds"

        # a random scene list name is created -- better error handling is needed
        # to ensure that the temporary scene list is removed even if scene-list-get
        # fails.
        list_id = _random_string()
        self.request(
            "scene-list-add",
            params={
                "listId": list_id,
                "datasetName": dataset,
                "idField": "displayId",
                param: display_id,
            },
        )
        r = self.request("scene-list-get", params={"listId": list_id})
        entity_id = [scene["entityId"] for scene in r]
        self.request("scene-list-remove", params={"listId": list_id})

        if param == "entityId":
            return entity_id[0]

        return entity_id

    def metadata(self, entity_id: str, dataset: str) -> dict:
        """Get metadata for a given scene.

        :param entity_id: entity id of the scene
        :param dataset: name of the scene dataset
        :return Scene metadata.
        """
        r = self.request(
            "scene-metadata",
            params={
                "datasetName": dataset,
                "entityId": entity_id,
                "metadataType": "full",
            },
        )
        return r

    def get_display_id(self, entity_id: str, dataset: str) -> str:
        """
        Get display ID from entity ID.

        :param entity_id: entity id of the scene
        :param dataset: Dataset alias.
        :return: display id of the scene
        """
        meta = self.metadata(entity_id, dataset)
        return meta["displayId"]

    def dataset_filters(self, dataset: str) -> list[dict]:
        """
        Return the result of a dataset-filters request

        :param dataset: Dataset alias.
        :return: result of the dataset-filters request
        """
        return self.request("dataset-filters", {"datasetName": dataset})

    def dataset_names(self) -> list[str]:
        """
        Return a list of all existing dataset
        """
        list_dataset = self.request("dataset-search")
        return [dataset["datasetAlias"] for dataset in list_dataset]

    def search(
        self,
        dataset: str,
        location: tuple[float, float] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        max_cloud_cover: int | None = None,
        date_interval: tuple[str, str] | None = None,
        months: list[int] | None = None,
        meta_filter: str | None = None,
        max_results: int | None = None,
    ) -> list[dict]:
        """
        Search for scenes, and return a list of all scenes found.
        Works with multiple adv_scene_search to get all scenes

        :param dataset: Alias dataset
        :param location: (longitude, latitude) of the point of interest.
        :param bbox: (xmin, ymin, xmax, ymax) of the bounding box.
        :param max_cloud_cover: Max. cloud cover in percent (1-100).
        :param date_interval: (start_date, end_date) of scene acquisition
        :param months: Limit results to specific months (1-12).
        :param meta_filter: String representation of metadata filter ex: camera=L
        :param max_results: Max. number of results. Return all if not provided
        :return: list of scene metadata
        """
        args = {
            "bbox": bbox,
            "max_cloud_cover": max_cloud_cover,
            "months": months,
            "meta_filter": meta_filter,
            "location": location,
            "date_interval": date_interval,
        }
        scene_filter = SceneFilter.from_args(**args)
        scenes = []
        for batch_scenes in self.batch_search(dataset, scene_filter, max_results):
            scenes += batch_scenes
        return scenes

    def batch_search(
        self,
        dataset: str,
        scene_filter: SceneFilter | None = None,
        max_results: int | None = None,
        metadata_type: str = "full",
        use_tqdm: bool = True,
        batch_size: int = 10000,
    ) -> Generator[list[dict], None, None]:
        """
        Return a Generator with each element is a list of 10000 (batch_size) scenes information.
        The scenes are filtered with the scene_filter given.

        :param dataset: Alias dataset
        :param scene_filter: Filter for the scene you want
        :param max_results: max scenes wanted, if None return all scenes found
        :param metadata_type: identifies which metadata to return (full|summary)
        :param use_tqdm: if True display a progress bar of the search
        :param batch_size: number of maxResults of each scene-search
        :return: generator of scenes information batch
        """
        starting_number = 1
        if use_tqdm:
            total = max_results if max_results else None
            p_bar = tqdm(desc="Import scenes metadata", total=total, unit="Scenes")

        while True:
            if max_results and starting_number + batch_size > max_results:
                batch_size = max_results - starting_number + 1
            scene_search = self.scene_search(
                dataset, scene_filter, batch_size, starting_number, metadata_type
            )
            yield scene_search["results"]
            starting_number = scene_search["nextRecord"]

            if use_tqdm:
                p_bar.n = starting_number - 1
                p_bar.total = (
                    max_results
                    if max_results and max_results <= scene_search["totalHits"]
                    else scene_search["totalHits"]
                )
                p_bar.refresh()

            if (
                max_results and scene_search["nextRecord"] > max_results
            ) or starting_number == scene_search["totalHits"]:
                break
        if use_tqdm:
            p_bar.n = p_bar.total
            p_bar.close()

    def scene_search(
        self,
        dataset: str,
        scene_filter: SceneFilter | None = None,
        max_results: int = 100,
        starting_number: int = 1,
        metadata_type: str = "full",
    ) -> dict:
        """Search for scenes.

        :param dataset: Case-insensitive dataset alias (e.g. landsat_tm_c1).
        :param scene_filter: Filter for the scene you want
        :param max_results: Max. number of results. Defaults to 100.
        :param starting_number: starting number of the search. Default 1
        :param metadata_type: identifies which metadata to return (full|summary)
        :return: Result of the scene-search request.
        """
        # we compile the metadataFilter if it exist to format it for the API
        if scene_filter and "metadataFilter" in scene_filter:
            scene_filter["metadataFilter"].compile(self.dataset_filters(dataset))

        r = self.request(
            "scene-search",
            params={
                "datasetName": dataset,
                "sceneFilter": scene_filter,
                "maxResults": max_results,
                "metadataType": metadata_type,
                "startingNumber": starting_number,
            },
        )
        return r

    def get_download_links(
        self,
        dataset: str,
        entity_ids: list[str],
        product_number: int | None = None,
        label: str = "usgsxplore",
    ):
        """
        Get all download URLs for the given dataset and entity IDs.

        :param dataset: Dataset name or alias.
        :param entity_ids: List of entity IDs to download.
        :param product_number: Index of the product to select if multiple are found.
            If None and multiple products are found, an exception is raised.
        :yield: dict {entityId: str, url: str, filesize: int}.

        Raises:
            DownloadOptionsError: If no available products are found, multiple options require a choice,
                                or the given product_number is invalid.
        """
        download_options = self.request(
            "download-options", {"datasetName": dataset, "entityIds": entity_ids}
        )
        download_options = process_download_options(download_options, product_number)

        download_list = [
            {"entityId": opt["entityId"], "productId": opt["id"]}
            for opt in download_options
        ]
        filesizes = {opt["entityId"]: opt["filesize"] for opt in download_options}
        download_request = self.request(
            "download-request", {"downloads": download_list, "label": label}
        )

        download_ids = []
        print(download_request)
        # first download all scenes in availableDownloads from the download-request
        for download in download_request["availableDownloads"]:
            download_ids.append(download["downloadId"])
            yield {
                "entityId": download["entityId"],
                "url": download["url"],
                "filesize": filesizes[download["entityId"]],
            }

        # then loop with download-retrieve request every 30 sec to get
        # all download link
        while True:
            retrieve_results = self.request("download-retrieve", {"label": label})
            print(retrieve_results)
            # loop in all link "available" and "requested" and download it
            # with the Product.download method
            for download in retrieve_results["available"]:
                if download["downloadId"] not in download_ids:
                    download_ids.append(download["downloadId"])
                    yield {
                        "entityId": download["entityId"],
                        "url": download["url"],
                        "filesize": filesizes[download["entityId"]],
                    }

            # if all the link are not ready yet, sleep 30 sec and loop, else exit from the loop
            if len(download_ids) < (
                len(download_list) - len(download_request["failed"])
            ):
                time.sleep(30)
            else:
                break

    def download(
        self,
        dataset: str,
        entity_ids: list[str],
        product_number: int | None = None,
        output_dir: str = ".",
        overwrite: bool = False,
        max_workers: int = 5,
        show_progress: bool = True,
        extract: bool = True,
        verbose: bool = False,
    ) -> None:
        """Download GTiff images identify from their entity id, use the M2M API.

        Args:
            dataset (str): Alias dataset of scenes wanted
            entity_ids (list[str]): list of entity id of scenes wanted
            product_number (int, optional): The product that will be download. Defaults to None.
            output_dir (str, optional): output directory to store GTiff images. Defaults to ".".
            overwrite (bool, optional): overwrite existing images. Defaults to False.
            max_workers (int, optional): maximum number of thread. Defaults to 5.
            show_progress (bool, optional): show a progress bar. Defaults to True.
            extract (bool, optional): extract in place images. Defaults to True.
            verbose (bool, optional): print information. Defaults to False.
        """
        # STEP 1 : VERIFYING OVERWRITE
        initial_count = len(entity_ids)
        if not overwrite and os.path.exists(output_dir):
            entity_ids = [
                eid
                for eid in entity_ids
                if not any(f.startswith(eid) for f in os.listdir(output_dir))
            ]
            skipped_count = initial_count - len(entity_ids)
            if verbose:
                print(f"[INFO] Skipped {skipped_count} already downloaded images")

        if not entity_ids:
            if verbose:
                print("[INFO] All requested images are already downloaded.")
            return

        # STEP 2 : FETCHING URLS
        if verbose:
            print(f"[INFO] Fetching download links for {len(entity_ids)} scenes...")
        label = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if show_progress:
            iter = tqdm(
                self.get_download_links(dataset, entity_ids, product_number, label),
                desc="Fetching links",
                total=len(entity_ids),
            )
        else:
            iter = self.get_download_links(dataset, entity_ids, product_number, label)
        urls = list(iter)

        # STEP 3 : DOWNLOADING SCENES
        if verbose:
            print(f"[INFO] Downloading {len(urls)} files to {output_dir}")
        download_scenes(urls, output_dir, max_workers, show_progress)

        # STEP 4 : EXTRACTING SCENES
        if extract:
            if verbose:
                print(f"[INFO] Extracting files in {output_dir}")
            extract_files_in_place(output_dir, show_progress, max_workers=max_workers)

        if verbose:
            print("[INFO] Download process completed.")

    def download_calibration_report(
        self,
        dataset: str,
        entity_id: str,
        output_dir: str = ".",
        calibration_report_product_id="D555",
    ) -> None:
        """
        Downloads the calibration report for a given dataset and entityId, and saves it to the specified directory.

        This method searches for available download options matching the given calibration report product ID,
        sends a download request, and writes the resulting file to disk.

        :param dataset: Name of the dataset to query.
        :param entity_id: The unique identifier of the entity (scene).
        :param output_dir: The directory where the calibration report will be saved. Defaults to the current directory.
        :param calibration_report_product_id: Product code for the calibration report. Defaults to "D555".
        :return: None
        :raises CalibrationReportNotFound: If no calibration report is available for the entity.
        :raises USGSError: If no downloadable file is returned after the request.
        """
        # Request available download options for the entity
        download_options = self.request(
            "download-options", {"datasetName": dataset, "entityIds": [entity_id]}
        )

        # Filter to find the calibration report by productCode
        calibrations_ids = [
            opt["id"]
            for opt in download_options
            if opt["available"] and opt["productCode"] == calibration_report_product_id
        ]

        # Raise an error if no calibration report was found
        if len(calibrations_ids) == 0:
            raise err.CalibrationReportNotFound("No calibration report found.")

        # Prepare download request with the found product ID
        download_list = [{"entityId": entity_id, "productId": calibrations_ids[0]}]
        request_results = self.request(
            "download-request", {"downloads": download_list, "label": "test"}
        )

        # Merge available and preparing downloads
        downloads = (
            request_results["availableDownloads"]
            + request_results["preparingDownloads"]
        )

        # Raise an error if no file is ready for download
        if len(downloads) == 0:
            raise err.USGSError("Download error.")

        # Extract the file download URL
        url = downloads[0]["url"]

        # Perform the actual download and save the file
        with requests.get(url, stream=True) as response:
            response.raise_for_status()

            # Extract filename from the 'Content-Disposition' header
            content_disposition = response.headers.get("Content-Disposition")
            filename = content_disposition.split("filename=")[1].strip('"')

            # Write the file to the output directory
            with open(os.path.join(output_dir, filename), "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:  # Skip keep-alive chunks
                        f.write(chunk)

    def clean_download(self) -> None:
        """
        This method clean residus of download in the API it first do
        a "download-order-remove", then it do a "download-search" and do a "download-remove" for each download.
        It called by the download method 2 times
        """
        self.request("download-order-remove", {"label": self.label})
        download_search = self.request("download-search", {"label": self.label})
        if download_search:
            for dl in download_search:
                self.request("download-remove", {"downloadId": dl["downloadId"]})


def _random_string(length=10):
    """Generate a random string."""
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


# End-of-file (EOF)
