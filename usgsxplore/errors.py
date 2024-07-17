"""
Description: module contain differents Error class

Last modified: 2024
Author: Luc Godin
"""


class USGSError(Exception):
    """General error with USGS API."""


class USGSInvalidEndpoint(Exception):
    """Endpoint is invalid."""


class USGSInvalidParametersError(Exception):
    """Provided parameters are invalid."""


class USGSUnauthorizedError(Exception):
    """User does not have access to the requested endpoint."""


class USGSAuthenticationError(Exception):
    """User credentials verification failed or API key is invalid."""


class USGSRateLimitError(Exception):
    """Account does not support multiple requests at a time."""


class APIInvalidParameters(Exception):
    """Invalid paramaters for the API class"""


class MetadataFilterError(Exception):
    """Error raise by MetadataFilter"""


class FilterMetadataValueError(Exception):
    """Error raise by MetadataValue"""


class AcquisitionFilterError(Exception):
    """Error raise by AcquisitionFilter"""


class SceneFilterError(Exception):
    """Error raise by SceneFilter"""
