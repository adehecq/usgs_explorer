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
from typing import Generator
from tqdm import tqdm

import requests

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

    def dataset_filters(self, dataset_name: str) -> list[dict]:
        """
        Return the result of a dataset-filters request

        :param dataset_name: Dataset alias.
        :return: result of the dataset-filters request
        """
        return self.request("dataset-filters", {"datasetName": dataset_name})

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


def _random_string(length=10):
    """Generate a random string."""
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


# End-of-file (EOF)
