"""
Description: module contain 2 classes useful for the downloading of scenes: ScenesDownloader and Product


Last modified: 2024
Author: Luc Godin
"""
import dataclasses
import os
import threading

import pandas as pd
import requests
from tqdm import tqdm


class ScenesDownloader:
    """
    This class is used to download Scenes using multi-thread.
    It can display the progress of the downloading in different way in terms of pbar_type value.
    - 0: display no progress bar
    - 1: display one static progress bar for all images download (don't display individual state)
    - 2: display a progress bar for each images downloading, also display the current state of it.

    """

    def __init__(
        self, entity_ids: list[str], output_dir: str, max_thread: int = 5, pbar_type: int = 2, overwrite: bool = False
    ) -> None:
        """
        This class is used to download Scenes using multi-thread.

        :param entity_ids: list of entity id of scenes that will be download
        :param output_dir: path of the output directory
        :param max_thread: max number of thread used for the downloading
        :param pbar_type: way to display progress bar (0: no pbar, 1: one pbar, 2: pbar for each scenes)
        :param overwrite: if false don't download images which are already in the output directory
        """
        # here we do list(set(...)) to remove duplicate ids
        self.df = pd.DataFrame({"entity_id": list(set(entity_ids))})
        self.df.set_index("entity_id", inplace=True)
        self.df = self.df.assign(product_id=None, display_id=None, filesize=None, url=None, progress=0, file_path=None)
        self._overwrite = overwrite
        self._output_dir = output_dir

        # attributes for the multi-thread management and the progression management
        self._threads = Threads([], threading.Semaphore(max_thread), threading.Event())
        self._progress = Progress(pbar_type, None, None)

    def set_download_options(self, download_options: list[dict]) -> None:
        """
        Update the dataframe self.df with values from the download_options.

        :param download_options: result of a download-options request
        """
        for download_option in download_options:
            if download_option["downloadSystem"] in ["dds", "ls_zip"]:
                entity_id = download_option["entityId"]
                self.df.loc[entity_id, "product_id"] = download_option["id"]
                self.df.loc[entity_id, "display_id"] = download_option["displayId"]
                self.df.loc[entity_id, "filesize"] = download_option["filesize"]

        # if not overwrite set already_download to True to scenes already downloaded
        if not self._overwrite:
            for filename in os.listdir(self._output_dir):
                file_path = os.path.join(self._output_dir, filename)
                if os.path.isfile(file_path) and filename.endswith((".tgz", ".tar")):
                    display_id = filename.split(".")[0]
                    self.df.loc[self.df["display_id"] == display_id, "file_path"] = file_path

        self._init_pbar()

    def get_downloads(self) -> list[dict]:
        """
        Return a list of dict formatted for M2M api download-request.
        The different dict represent a product contain in self.download

        :return: downloads
        """
        res = []
        selected_cols = self.df.loc[self.get_states() == Product.STATE_NO_LINK]

        for entity_id, row in selected_cols.iterrows():
            res.append({"entityId": entity_id, "productId": row["product_id"]})
        return res

    def get_states(self) -> pd.Series:
        """
        return a searies with product state
        """

        return self.df.apply(Product.get_product_state, axis=1)

    def download(self, entity_id: str, url: str) -> None:
        """
        This method create a thread to download the scenes identify with it's entity_id.

        :param entity_id: entity id of the scenes that will be download
        :param url: url of downloading
        """
        self.df.loc[entity_id, "url"] = url
        self._update_pbar()
        thread = threading.Thread(
            target=self._download_worker,
            args=(entity_id,),
            daemon=True,
        )
        self._threads.threads.append(thread)
        thread.start()

    def _download_worker(self, entity_id: str) -> None:
        """
        Download the images with the url in the dataframe associate to the entity_id given.
        Every 5 Mo update the progress in the dataframe and update progress bar.
        This method is designed to be in a thread

        :param entity_id: entity id of the scene to download
        """
        if self._threads.stop_event.is_set():  # if the stop event is set return
            return

        with self._threads.sema:
            # do a get request with the url in the dataframe
            response = requests.get(self.df.loc[entity_id, "url"], stream=True, timeout=600)
            response.raise_for_status()

            # recup the filename of the scene to set the file_path of the scene
            content_disposition = response.headers.get("Content-Disposition")
            filename = content_disposition.split("filename=")[1].strip('"')
            self.df.loc[entity_id, "file_path"] = os.path.join(self._output_dir, filename)

            # recup the reel filesize of the scene to update the df
            self.df.loc[entity_id, "filesize"] = int(response.headers.get("content-length", 0))

            self._update_pbar()

            block_size = 5000 * 1024  # 5 Mo

            with open(self.df.loc[entity_id, "file_path"], "wb") as file:
                for data in response.iter_content(block_size):
                    # test if the stop event is set
                    if self._threads.stop_event.is_set():
                        break
                    file.write(data)
                    self.df.loc[entity_id, "progress"] += len(data)

                    # update the pbar depend on the type of it
                    if self._progress.type == 1:
                        self._progress.static_pbar.update(len(data))
                    elif self._progress.type == 2:
                        self._progress.pbars[entity_id].update(len(data))

            # test if the file is corrupted to remove it, else update the state of it
            if self.get_states()[entity_id] != Product.STATE_DOWNLOADED:
                os.remove(self.df.loc[entity_id, "file_path"])

            self._update_pbar()

    def wait_all_thread(self) -> None:
        """
        Wait all thread to finish the downloading
        """
        for thread in self._threads.threads:
            thread.join()

    def stop_download(self) -> None:
        """
        Force the stop of the downloading
        """
        self._threads.stop_event.set()
        self.wait_all_thread()

    # ----------------------------------------------------------------------------------------------------
    # 									METHODS FOR PBAR
    # ----------------------------------------------------------------------------------------------------
    def _init_pbar(self) -> None:
        """
        This method init progress bar.
        - _pbar_type == 0: don't do anythings
        - _pbar_type == 1: init one static pbar
        - _pbar_type == 2: init a pbar for each product which are going to be download
        """
        if self._progress.type == 1:
            self._progress.static_pbar = tqdm(unit="Kb", unit_scale=True)
            self._update_pbar()
        elif self._progress.type == 2:
            self._progress.pbars = {}
            for entity_id, state in self.get_states().items():
                if state >= Product.STATE_NO_LINK:
                    self._progress.pbars[entity_id] = tqdm(unit="Kb", unit_scale=True)
            self._update_pbar()

    def _update_pbar(self) -> None:
        """
        This method update the description and the total of pbar depend on the _pbar_type
        """
        if self._progress.type == 1:
            states = self.get_states()

            # the total of the static pbar correspond to the sum of all filesize of scenes to download
            self._progress.static_pbar.total = sum(self.df.loc[states >= Product.STATE_NO_LINK, "filesize"])

            # the description correspond of downloading counter
            total_scenes = sum(states >= Product.STATE_NO_LINK)  # total number of scenes to download
            scenes_dl = sum(states == Product.STATE_DOWNLOADED)  # number of scenes download
            self._progress.static_pbar.set_description(f"Downloading {scenes_dl}/{total_scenes}")
        elif self._progress.type == 2:
            states = self.get_states()
            products = self.df.loc[states >= Product.STATE_NO_LINK]

            # loop on product that are in downloading
            for entity_id, row in products.iterrows():
                # the total of each pbar correspond of the filesize of the corresponding scenes
                self._progress.pbars[entity_id].total = row["filesize"]

                # the description is the id of the scenes plus the current state
                str_state = Product.state_map[states[entity_id]]
                self._progress.pbars[entity_id].set_description(f"{entity_id}-({str_state})")


class Product:
    """
    Static class used only to manage state of Product. A product is a row of the df of ScenesDownloader
    """

    STATE_UNEXIST = 0
    STATE_UNAVAILABLE = 1
    STATE_ALREADY_DL = 2
    STATE_NO_LINK = 3
    STATE_LINK_READY = 4
    STATE_DOWNLOADING = 5
    STATE_DOWNLOADED = 6

    state_map = {
        STATE_UNEXIST: "unexist",
        STATE_UNAVAILABLE: "unavailable",
        STATE_ALREADY_DL: "already downloaded",
        STATE_NO_LINK: "no link",
        STATE_LINK_READY: "link ready",
        STATE_DOWNLOADING: "downloading",
        STATE_DOWNLOADED: "downloaded",
    }

    @classmethod
    def get_product_state(cls, row) -> int:
        """
        return the product state
        """
        if row["product_id"] is None:
            state = cls.STATE_UNEXIST
        elif row["filesize"] == 0:
            state = cls.STATE_UNAVAILABLE
        elif row["file_path"] is not None and row["url"] is None:
            state = cls.STATE_ALREADY_DL
        elif row["url"] is None:
            state = cls.STATE_NO_LINK
        elif row["file_path"] is None:
            state = cls.STATE_LINK_READY
        elif row["progress"] < row["filesize"]:
            state = cls.STATE_DOWNLOADING
        else:
            state = cls.STATE_DOWNLOADED
        return state


@dataclasses.dataclass
class Threads:
    """
    dataclasses contain parameters for multi-thread management.
    """

    threads: list[threading.Thread]
    sema: threading.Semaphore
    stop_event: threading.Event


@dataclasses.dataclass
class Progress:
    """
    dataclasses contain parameters for the display of progress bars.
    """

    type: int
    static_pbar: tqdm | None
    pbars: dict[str, tqdm] | None


# End-of-file (EOF)
