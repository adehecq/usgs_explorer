"""
Description: module contain different Error class

Last modified: 2024
Author: Luc Godin
"""
import pandas as pd


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


class USGSInvalidDataset(Exception):
    """The dataset name is invalid"""


class APIInvalidParameters(Exception):
    """Invalid parameters for the API class"""


class MetadataFilterError(Exception):
    """Error raise by MetadataFilter"""


class FilterMetadataValueError(Exception):
    """Error raise by MetadataValue"""


class FilterFieldError(Exception):
    """Error raise when the field value of a filter is incorrect"""

    def __init__(self, field: str, field_ids: list[str], field_labels: list[str], field_sql: list[str]) -> None:
        self.df = pd.DataFrame({"field_id": field_ids, "field_label": field_labels, "sql_field": field_sql})
        self.field = field

    def __str__(self) -> str:
        return f"Invalid field '{self.field}', choose one in :\n{str(self.df)}"


class FilterValueError(Exception):
    """Error raise when the value of a filter is incorrect"""

    def __init__(self, value: str, values: list[str], value_labels: list[str]) -> None:
        self.df = pd.DataFrame(
            {
                "values": values,
                "value_labels": value_labels,
            }
        )
        self.value = value

    def __str__(self) -> str:
        return f"Invalid value '{self.value}', choose one in :\n{str(self.df)}"


class AcquisitionFilterError(Exception):
    """Error raise by AcquisitionFilter"""


class SceneFilterError(Exception):
    """Error raise by SceneFilter"""


class ScenesNotFound(Exception):
    """Error raise when no scenes are founds"""


class CalibrationReportNotFound(Exception):
    """Error raise when no calibration report are founds"""


class DownloadOptionsError(Exception):
    """Custom exception for errors during download options processing."""
