"""
Description: module contain the API class to download and interact with the USGS api (https://m2m.cr.usgs.gov/api/docs/json/).
This class is highly inspirate from https://github.com/yannforget/landsatxplore.

Last modified: 2024
Author: Luc Godin
"""

import json
from urllib.parse import urljoin
import string
import random
import time
import os
import signal
from typing import Generator
from tqdm import tqdm

import requests

from usgsxplore.downloader.product import Product
from usgsxplore.errors import USGSAuthenticationError, USGSError, USGSRateLimitError, APIInvalidParameters
from usgsxplore.filter import SceneFilter


API_URL = "https://m2m.cr.usgs.gov/api/api/json/stable/"


class API:
    """EarthExplorer API."""

    def __init__(self, username: str, password: str|None = None, token: str|None = None) -> None:
        """EarthExplorer API.

        :param username: EarthExplorer username.
        :param password: EarthExplorer password.
        :param token: EarthExplorer token.  
        """
        self.url = API_URL
        self.session = requests.Session()
        self.label = "usgsxplore"
        self.login(username, password, token)

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
                raise USGSAuthenticationError(f"{error_code}: {error_msg}.")
            if error_code == "RATE_LIMIT":
                raise USGSRateLimitError(f"{error_code}: {error_msg}.")
            raise USGSError(f"{error_code}: {error_msg}.")

    def request(self, endpoint: str, params: dict=None) -> dict:
        """Perform a request to the USGS M2M API.
        :param endpoint: API endpoint.
        :param params: API parameters.
        :raise USGSAuthenticationError: If credentials are not valid of if user lacks permission.
        :raise USGSRateLimitError: If there are too many request
        :return: JSON data returned by the USGS API.
        """
        url = urljoin(self.url, endpoint)
        data = json.dumps(params)
        r = self.session.get(url, data=data)
        try:
            self.raise_api_error(r)
        except USGSRateLimitError:
            time.sleep(3)
            r = self.session.get(url, data=data)
        self.raise_api_error(r)
        return r.json().get("data")

    def login(self, username: str, password: str|None = None, token: str|None = None) -> None:
        """Get an API key. With either the login request or the login-token-request

        :param username: EarthExplorer username.
        :param password: EarthExplorer password.
        :param token: EarthExplorer token. 
        :raise APIInvalidParameters: if password and token are None.
        :raise USGSAuthenticationError: If the authentification failed
        """
        if password is None and token is None:
            raise APIInvalidParameters("Either password or token need to be given.")
        if token is not None:
            login_url = urljoin(self.url, "login-token")
            payload = {"username": username, "token": token}
        else:
            login_url = urljoin(self.url, "login")
            payload = {"username": username, "password": password}
        r = self.session.post(login_url, json.dumps(payload))
        self.raise_api_error(r)
        self.session.headers["X-Auth-Token"] = r.json().get("data")

    def logout(self) -> None:
        """Logout from USGS M2M API."""
        self.request("logout")
        self.session = requests.Session()

    def get_entity_id(self, display_id: str|list[str], dataset: str) -> str|list[str]:
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

    def search(
        self,
        dataset: str,
        location: tuple[float, float]|None = None,
        bbox: tuple[float, float, float, float]|None = None,
        max_cloud_cover: int|None = None,
        date_interval: tuple[str,str]|None = None,
        months: list[int]|None = None,
        meta_filter: str|None = None,
        max_results: int|None = None
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
        """
        args = {
            "bbox":bbox, "max_cloud_cover":max_cloud_cover, "months":months,
            "meta_filter":meta_filter
        }
        if location:
            args.update({"longitude":location[0], "latitude":location[1]})
        if date_interval:
            args.update({"start_date":date_interval[0], "end_date":date_interval[1]})

        scene_filter = SceneFilter.from_args(**args)
        scenes = []
        for batch_scenes in self.batch_search(dataset, scene_filter, max_results):
            scenes += batch_scenes
        return scenes

    def batch_search(
        self,
        dataset: str,
        scene_filter: SceneFilter | None = None,
        max_results: int|None = None,
        metadata_type: str|None="full",
        use_tqdm: bool = True,
        batch_size: int = 10000
    ) -> Generator[list[dict], None, None]:
        """
        Return a Generator with each element is a list of 10000 (batch_size) scenes informations.
        The scenes are filtered with the scene_filter given.

        :param dataset: Alias dataset
        :param scene_filter: Filter for the scene you want
        :param max_results: max scenes wanted, if None return all scenes found
        :param metadata_type: identifies wich metadata to return (full|summary|None)
        :param use_tqdm: if True display a progress bar of the search
        :param batch_size: number of maxResults of each scene-search
        :return: generator of scenes informations batch 
        """
        starting_number = 1
        if use_tqdm:
            total = max_results if max_results else None
            p_bar = tqdm(desc="Import scenes metadata", total=total, unit="Scenes")

        while True:
            if max_results and starting_number + batch_size > max_results:
                batch_size = max_results - starting_number + 1
            scene_search = self.scene_search(dataset, scene_filter, batch_size, starting_number, metadata_type)
            yield scene_search["results"]
            starting_number = scene_search["nextRecord"]

            if use_tqdm:
                p_bar.n = starting_number - 1
                p_bar.total = max_results if max_results and max_results <= scene_search["totalHits"] else scene_search["totalHits"]
                p_bar.refresh()

            if (max_results and scene_search["nextRecord"] > max_results) or starting_number == scene_search["totalHits"]:
                break
        if use_tqdm:
            p_bar.n = p_bar.total
            p_bar.close()

    def scene_search(
        self,
        dataset: str,
        scene_filter: SceneFilter | None = None,
        max_results: int=100,
        starting_number: int=1,
        metadata_type: str|None="full"
    ) -> dict:
        """Search for scenes.

        :param dataset: Case-insensitive dataset alias (e.g. landsat_tm_c1).
        :param scene_filter: Filter for the scene you want
        :param max_results: Max. number of results. Defaults to 100.
        :param starting_number: starting number of the search. Default 1
        :param metadata_type: identifies wich metadata to return (full|summary|None)
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
                "startingNumber": starting_number
            },
        )
        return r

    def download(self, dataset: str, entity_ids: list[str], output_dir: str = ".", p_bar_type: int = 2) -> None:
        """
        Download GTiff images identify from their entity id, use the M2M API. This method
        can display progression and recap in terms of the verbosity given.

        :param dataset: Alias dataset of scenes wanted
        :param entity_ids: list of entity id of scenes wanted
        :param output_dir: output directory to store GTiff images
        """

        # first get the download-option with the process_download_options method
        products, downloaded_ids, unavailable_ids, unmatch_ids = self.process_download_options(dataset, entity_ids, output_dir)

        # next remove all the last download-request and download
        # to start a new download properly
        self.request("download-order-remove",{"label":self.label})
        download_search = self.request("download-search",{"label":self.label})
        if download_search:
            for dl in download_search:
                self.request("download-remove",{"downloadId":dl["downloadId"]})

        # send a download-request with parsed products
        download_list = [products[entity_id].to_dict() for entity_id in products]
        request_results = self.request("download-request", {"downloads":download_list,"label": self.label})

        # defined the ctrl-c signal to stop all downloading thread 
        signal.signal(signal.SIGINT, _handle_sigint)

        # then loop with download-retrieve request every 30 sec to get
        # all download link
        download_ids = []
        while True :
            retrieve_results = self.request("download-retrieve", {"label":self.label})

            # loop in all link "available" and "requested" and download it
            # with the Product.download method
            for download in retrieve_results["available"] + retrieve_results["requested"]:
                if download["downloadId"] not in download_ids:
                    download_ids.append(download["downloadId"])
                    products[download["entityId"]].download(download["url"], output_dir)

            # if all the link are not ready yet, sleep 30 sec and loop, else exit from the loop
            if len(download_ids) < (len(download_list) - len(request_results["failed"])):
                time.sleep(30)
            else:
                break

        # cleanup the download order and wait all thread to finish
        self.request("download-order-remove",{"label":self.label})
        Product.wait_end_downloading()

    def process_download_options(
        self, dataset: str, entity_ids: list[str], output_dir: str
    )-> tuple[dict[str, Product], list[str], list[str], list[str]]:
        """
        Process download options to return 4 informations:
            - products: dict identifie with entity id of product to download
            - downloaded_ids: list of entity id that already in output_dir
            - unavailable_ids: list of entity id that are not available
            - unmatch_ids: list of ids wich not exist in the database

        :param dataset: Dataset alias of the scenes
        :param entity_ids: entity ids of the scenes
        :param output_dir: path of the output directory
        :return: (products, downloaded_ids, unavailable_ids, unmatch_ids)
        """

        products = {}
        downloaded_ids = []
        unavailable_ids = []
        unmatch_ids = entity_ids.copy()
        
        # get the display id of all images already download in the output_dir
        _downloaded_dids = []
        for filename in os.listdir(output_dir):
            if os.path.isfile(os.path.join(output_dir, filename)) and filename.endswith((".tgz",".tar")):
                _downloaded_dids.append(filename.split(".")[0])

        # do the download-options request
        download_options = self.request("download-options", {"datasetName":dataset, "entityIds":entity_ids})

        # Process the result of it
        for download_option in download_options:
            if download_option["downloadSystem"] in ['dds', 'ls_zip']:
                unmatch_ids.remove(download_option["entityId"])

                # check if the product is available if not we append it's id to the unavailable_ids
                if download_option["available"]:

                    # here the product is available, but we also check if it's already download
                    # if not we append this to products else we append to downloaded_ids
                    if download_option["displayId"] not in _downloaded_dids:
                        products[download_option["entityId"]] = Product.from_download_option(download_option)
                    else:
                        downloaded_ids.append(download_option["entityId"])
                else:
                    unavailable_ids.append(download_option["entityId"])
        return (products, downloaded_ids, unavailable_ids, unmatch_ids)

def _random_string(length=10):
    """Generate a random string."""
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))

def _handle_sigint(signal, frame):
    Product.stop_downloading()
    exit(0)

# End-of-file (EOF)
