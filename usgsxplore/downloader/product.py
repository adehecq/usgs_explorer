"""
Description: module contain the Product class use for the downloading of images.

Last modified: 2024
Author: Luc Godin
"""
import threading
import os
import requests
from tqdm import tqdm


class Product:
    """
    This class manage the downloading of the product. It use multi-thread to download GTiff images.
    It can display a progress bar of the downloading.
    """
    # static const use for the state of the downloading
    DL_STATE_NO_LINK = "no link"
    DL_STATE_LINK = "link ready"
    DL_STATE_DOWNLOADING = "downloading"
    DL_STATE_DOWNLOADED = "downloaded"
    DL_STATE_OWNED = "already downloaded"

    use_tqdm = True

    # Static attributes use to manage the multi-thread downloading
    _sema = threading.Semaphore(value=5)
    _threads: list[threading.Thread] = []
    _stop_event = threading.Event()

    def __init__(self, entity_id: str, product_id: str, file_size: str) -> None:
        self.entity_id = entity_id
        self.product_id = product_id
        self.file_size = file_size
        self._progress = 0

        if self.use_tqdm and self.file_size:
            self.p_bar = tqdm(total=self.file_size, unit="Kb", unit_scale=True)

        self.set_dl_state(self.DL_STATE_NO_LINK)

    def to_dict(self) -> dict[str, str]:
        "Return a dict for the downloading"
        return {"entityId": self.entity_id, "productId": self.product_id}

    @classmethod
    def from_download_option(cls, download_option: dict) -> 'Product':
        """
        Create an instance of Product from the download-option result

        :param download_option: download-option result of one product
        :return: Product instance
        """
        return cls(download_option["entityId"], download_option["id"], download_option["filesize"])

    def download(self, url: str, output_dir: str) -> None:
        """
        This method download the GTiff image, with the URL given.
        It supposed to be the image correspond to the product.
        It start a thread to download it

        :param url: url of the GTiff image to be download
        :param output_dir: path of the output directory
        """
        self.set_dl_state(self.DL_STATE_LINK) # download link is ready

        # create a daemon thread to download the GTiff image
        thread = threading.Thread(
            target=self._download_worker,
            args=(
                url,
                output_dir,
            ),
            daemon=True,
        )
        self._threads.append(thread)
        thread.start()

    def _download_worker(self, url: str, output_dir: str) -> None:
        """
        This method download the GTiff image, with the URL given.
        It used to be in a thread. It have progress value and can update a p_bar if set.
        The thread stop if the the _stop_event is set.

        :param url: url of the GTiff image to be download
        :param output_dir: path of the output directory
        """
        if self._stop_event.is_set():  # if the stop event is set return
            return
        with self._sema:
            try:
                self.set_dl_state(self.DL_STATE_DOWNLOADING)
                response = requests.get(url, stream=True, timeout=600)
                response.raise_for_status()
                content_disposition = response.headers.get("Content-Disposition")
                filename = content_disposition.split("filename=")[1].strip('"')

                block_size = 5000 * 1024  # 5 Mo

                file_path = os.path.join(output_dir, filename)
                with open(file_path, "wb") as file:
                    for data in response.iter_content(block_size):
                        # test if the stop event is set
                        if self._stop_event.is_set():
                            break
                        file.write(data)
                        self.set_progress(file.tell()) # set the progress of the downloading
                if self._progress < self.file_size:
                    os.remove(file_path)
                    if self.use_tqdm:
                        self.p_bar.close()
                else:
                    self.set_dl_state(self.DL_STATE_DOWNLOADED)

            except requests.RequestException as e:
                self.set_dl_state(f"error: {str(e)}")

    def set_dl_state(self, value: str) -> None:
        """
        Set the downloading state, if p_bar is used display the state in the description.
        :param value: state value
        """
        self._dl_state = value

        if self.use_tqdm:
            self.p_bar.set_description(f"{self.entity_id}-({self._dl_state})")
            if value == self.DL_STATE_DOWNLOADING:
                self.p_bar.reset()

    def set_progress(self, value: int) -> None:
        """
        Set the progress of the downloading, and update the progress bar if it's set
        """
        if value > self.file_size:
            self._progress = self.file_size
        else:
            self._progress = value

        #update of the progress bar
        if self.use_tqdm:
            self.p_bar.n = self._progress
            self.p_bar.refresh()

    def get_dl_state(self) -> str:
        "return the downloading state"
        return self._dl_state

    def get_progress(self) -> int:
        return self._progress

    @classmethod
    def stop_downloading(cls) -> None:
        "Stop the downloading of all product instance"
        cls._stop_event.set()
        cls.wait_end_downloading()

    @classmethod
    def wait_end_downloading(cls) -> None:
        "Wait to complete all downloading of all product instance"
        for thread in cls._threads:
            thread.join()

# End-of-file (EOF)
