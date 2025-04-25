import os

import pytest

from usgsxplore.api import API


@pytest.fixture(scope="session")
def api():
    """
    Initializes the API client for the whole test session and logs out after all tests are done.

    :return: An authenticated instance of the API client.
    """
    api = API(os.getenv("USGS_USERNAME"), os.getenv("USGS_TOKEN"))
    yield api
    api.logout()


@pytest.fixture(scope="session")
def declassii_filters(api: API) -> list[dict]:
    """
    Fetches the dataset filters for 'declassii' only once per test session.

    :param api: The authenticated API client.
    :return: Filters dictionary for 'declassii' dataset.
    """
    return api.dataset_filters("declassii")
