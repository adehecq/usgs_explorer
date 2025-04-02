"""
Description: this module contain multiple class for SceneFilter

Last modified: 2024
Author: Luc Godin
"""
from datetime import datetime

import geopandas as gpd
from shapely.geometry import Point, mapping

from usgsxplore.errors import (
    AcquisitionFilterError,
    FilterFieldError,
    FilterMetadataValueError,
    FilterValueError,
    MetadataFilterError,
    SceneFilterError,
)


class Coordinate(dict):
    """A coordinate object as expected by the USGS M2M API."""

    def __init__(self, longitude: float, latitude: float) -> None:
        """
        A coordinate object as expected by the USGS M2M API.

        :param longitude: Decimal longitude.
        :param latitude: Decimal latitude.
        """
        self["longitude"] = longitude
        self["latitude"] = latitude


class GeoJson(dict):
    """A GeoJSON object as expected by the USGS M2M API."""

    def __init__(self, shape: dict):
        """ "
        A GeoJSON object as expected by the USGS M2M API.
        :param shape: Input geometry as a geojson-like dict.
        """
        self["type"] = shape["type"]
        self["coordinates"] = shape["coordinates"]

    @staticmethod
    def transform(geom_type: str, coordinates) -> list[list[Coordinate]] | list[Coordinate] | Coordinate:
        """Convert geojson-like coordinates as expected by the USGS M2M API.
        :param geom_type: type of the geometry will be used MultiPolygon|Polygon|LineString|Point
        :param coordinates: coordinate associate to the geom_type
        :return: coordinates as expected by the USGS M2M API
        """
        if geom_type == "MultiPolygon":
            return [[[Coordinate(*point) for point in polygon] for polygon in multi_poly] for multi_poly in coordinates]
        if geom_type == "Polygon":
            return [[Coordinate(*point) for point in polygon] for polygon in coordinates]
        if geom_type == "LineString":
            return [Coordinate(*point) for point in coordinates]
        if geom_type == "Point":
            return Coordinate(*coordinates)
        raise ValueError(f"Geometry type `{geom_type}` not supported.")


class SpatialFilterMbr(dict):
    """Bounding box spatial filter."""

    def __init__(self, xmin: float, ymin: float, xmax: float, ymax: float):
        """
        Bounding box spatial filter.
        :param xmin: Min. decimal longitude.
        :param ymin: Min. decimal latitude.
        :param xmax: Max. decimal longitude.
        :param ymax: Max. decimal latitude.
        """
        self["filterType"] = "mbr"
        self["lowerLeft"] = Coordinate(xmin, ymin)
        self["upperRight"] = Coordinate(xmax, ymax)


class SpatialFilterGeoJSON(dict):
    """GeoJSON-based spatial filter."""

    def __init__(self, shape: dict):
        """
        GeoJSON-based spatial filter.

        :param shape: Input shape as a geojson-like dict.
        """
        self["filterType"] = "geojson"
        self["geoJson"] = GeoJson(shape)

    @classmethod
    def from_file(cls, file_path: str):
        # read the geopsatial file with geopandas
        gdf = gpd.read_file(file_path)

        # transform the coordinate into EPSG:4326
        if gdf.crs != "EPSG:4326":
            gdf.to_crs(epsg=4326, inplace=True)

        # create a combine of all geometry into a big one and create instance with it
        shape = mapping(gdf.geometry.union_all())  # mapping(unary_union(gdf.geometry))
        return cls(shape)


class AcquisitionFilter(dict):
    """Acquisition date filter."""

    def __init__(self, start: str, end: str):
        """
        Acquisition date filter.

        :param start: ISO 8601 start date. ex "2010-01-01"
        :param end: ISO 8601 end date.ex "2011-01-31"
        """
        if not self.is_iso_date(start):
            raise AcquisitionFilterError(f"the start date '{start}', need to be format like '2010-01-01'")
        if not self.is_iso_date(end):
            raise AcquisitionFilterError(f"the end date '{end}', need to be format like '2010-01-01'")

        self["start"] = start
        self["end"] = end

    @staticmethod
    def is_iso_date(str_date: str) -> bool:
        """
        Return true if the str_date is in iso 8601 format

        :param str_date: string representation of the date tested
        :return: True if the str_date is in iso 8601 format
        """
        try:
            datetime.strptime(str_date, "%Y-%m-%d")
            return True
        except ValueError:
            return False


class CloudCoverFilter(dict):
    """Cloud cover filter."""

    def __init__(self, min_cc: int = 0, max_cc: int = 100, include_unknown: bool = False):
        """
        Cloud cover filter.
        :param min_cc: Min. cloud cover in percents (default=0).
        :param max_cc: Max. cloud cover in percents (default=100).
        :param include_unknown: Include scenes with unknown cloud cover (default=False).
        """
        self["min"] = min_cc
        self["max"] = max_cc
        self["includeUnknown"] = include_unknown


class MetadataFilter(dict):
    """Metadata filter."""

    @classmethod
    def from_str(cls, str_repr: str) -> "MetadataFilter":
        """
        Create an instance of MetadataFilter with a string representation.
        Example of string representation : "field1=value1 & field2=value2"

        :param str_repr: string representation of the filter
        """
        if "&" not in str_repr and "|" not in str_repr:
            return MetadataValue.from_str(str_repr)

        for char in str_repr:
            if char == "&":
                split_str = str_repr.split("&", maxsplit=1)
                return MetadataValue.from_str(split_str[0]) & cls.from_str(split_str[1])
            if char == "|":
                split_str = str_repr.split("|", maxsplit=1)
                return MetadataValue.from_str(split_str[0]) | cls.from_str(split_str[1])

        raise MetadataFilterError(f"'{str_repr}' is not a valid string representation, ex:camera=H & camera_resol=6 ")

    def compile(self, dataset_filters: list[dict]) -> None:
        if "childFilters" in self:
            for f in self["childFilters"]:
                f.compile(dataset_filters)

    def __and__(self, other):
        """
        Redefined the __and__ method to create a MetadataAnd type.
        See : https://m2m.cr.usgs.gov/api/docs/datatypes/#metadataAnd

        :param other: MetadataFilter or any but the and is defined only for MetadataFilter
        :return: MetadataFilter and
        ### Example
        ```
        # f is a MetadataAnd
        f = MetadataValue("camera_resol","6") & MetadataValue("camera","H")
        ```
        """
        if isinstance(other, MetadataFilter):
            mf_and = MetadataFilter()
            mf_and["filterType"] = "and"
            mf_and["childFilters"] = [self, other]
            return mf_and
        return NotImplemented

    def __or__(self, other):
        """
        Redefined the __or__ method to create a MetadataOr type.
        See : https://m2m.cr.usgs.gov/api/docs/datatypes/#metadataOr

        :param other: MetadataFilter or any but the or is defined only for MetadataFilter
        :return: MetadataFilter or
        ### Example
        ```
        # f is a MetadataOr
        f = MetadataValue("camera_resol","6") | MetadataValue("camera","H")
        ```
        """
        if isinstance(other, MetadataFilter):
            mf_or = MetadataFilter()
            mf_or["filterType"] = "or"
            mf_or["childFilters"] = [self, other]
            return mf_or
        return NotImplemented


class MetadataValue(MetadataFilter):
    """
    Metadata value

    ### Example
    ```{python}
    # when all filter are compiled f1 == f2 == f3
    f1 = MetadataValue("5e839ff8388465fa","6")
    f2 = MetadataValue("Camera Resolution","2 to 4 feet")
    f3 = MetadataValue("camera_resol","6")
    ```
    """

    def __init__(self, field: str, value: str):
        """
        Metadata value

        :param field: field id or filed name or sql var name
        :param value: value or value label for the filter


        ### Example
        ```{python}
        # when all filter are compiled f1 == f2 == f3
        f1 = MetadataValue("5e839ff8388465fa","6")
        f2 = MetadataValue("Camera Resolution","2 to 4 feet")
        f3 = MetadataValue("camera_resol","6")
        ```
        """
        self._field = field
        self._value = value
        self["filterType"] = "value"
        if isinstance(value, str):
            self["operand"] = "like"
        else:
            self["operand"] = "="

    @classmethod
    def from_str(cls, str_repr: str) -> "MetadataValue":
        """
        Constructor with string representation.
        The string representation work like this "field=value".
        You can also add space or guillemet: "field = value", "'field' = 'value'"

        :param str_repr: string representation of the MetadataValue ex "camera=H"
        """
        if "=" not in str_repr:
            raise FilterMetadataValueError(f"'{str_repr}' is not a valid string representation, ex:camera=H")
        split_str = str_repr.split("=", maxsplit=1)
        field = split_str[0].replace('"', "").replace("'", "").strip()
        value = split_str[1].replace('"', "").replace("'", "").strip()
        return cls(field, value)

    def compile(self, dataset_filters: list[dict]) -> None:
        """
        This method compile the filter to transform it into a valid MetadataValue for the API.

        :param dataset_filters: need to be the result of a dataset-filters request on the dataset.
        """
        for f in dataset_filters:
            sql_value = f["searchSql"].split(" ", maxsplit=1)[0]
            if self._field in (f["id"], f["fieldLabel"], sql_value):
                self["filterId"] = f["id"]
                if "valueList" in f:
                    for value, label in f["valueList"].items():
                        if self._value in (value, label):
                            self["value"] = value
                    if "value" not in self:
                        values = list(f["valueList"].keys())
                        value_labels = list(f["valueList"].values())

                        raise FilterValueError(self._value, values, value_labels)
                else:
                    self["value"] = self._value

        if "filterId" not in self:
            field_ids = [f["id"] for f in dataset_filters]
            field_labels = [f["fieldLabel"] for f in dataset_filters]
            field_sql = [f["searchSql"].split(" ", maxsplit=1)[0] for f in dataset_filters]

            raise FilterFieldError(self._field, field_ids, field_labels, field_sql)


class SceneFilter(dict):
    """Scene search filter."""

    def __init__(
        self,
        acquisition_filter: AcquisitionFilter | None = None,
        spatial_filter: SpatialFilterMbr | SpatialFilterGeoJSON | None = None,
        cloud_cover_filter: CloudCoverFilter | None = None,
        metadata_filter: MetadataFilter | None = None,
        months: list[int] | None = None,
    ):
        """
        Scene search filter.

        :param acquisition_filter: Acquisition date filter.
        :param spatial_filter: Spatial filter.
        :param cloud_cover_filter: Cloud cover filter.
        :param metadata_filter: Metadata filter.
        :param months: Seasonal filter (month numbers from 1 to 12).
        """
        if acquisition_filter:
            self["acquisitionFilter"] = acquisition_filter
        if spatial_filter:
            self["spatialFilter"] = spatial_filter
        if cloud_cover_filter:
            self["cloudCoverFilter"] = cloud_cover_filter
        if metadata_filter:
            self["metadataFilter"] = metadata_filter
        if months:
            self["seasonalFilter"] = months

    @classmethod
    def from_args(cls, **kwargs):
        """
        Create a SceneFilter instance with kwargs given.

        param kwargs: arguments for filter: location, bbox, g_file, max_cloud_cover, date_interval, months, meta_filter
        """
        # first test if all kwargs are valid if not raise an Exception
        valid_args = ["location", "bbox", "g_file", "max_cloud_cover", "date_interval", "months", "meta_filter"]
        invalid_args = [arg for arg in kwargs if arg not in valid_args]
        if invalid_args:
            raise SceneFilterError(f"Invalid arguments: {', '.join(invalid_args)}")

        spatial_filter = None
        if "g_file" in kwargs and kwargs["g_file"]:
            spatial_filter = SpatialFilterGeoJSON.from_file(kwargs["g_file"])
        elif "location" in kwargs and kwargs["location"] and len(kwargs["location"]) == 2:
            spatial_filter = SpatialFilterMbr(*Point(*kwargs["location"]).bounds)
        elif "bbox" in kwargs and kwargs["bbox"]:
            spatial_filter = SpatialFilterMbr(*kwargs["bbox"])

        acquisition_filter = None
        if "date_interval" in kwargs and kwargs["date_interval"] and len(kwargs["date_interval"]) == 2:
            acquisition_filter = AcquisitionFilter(*kwargs["date_interval"])

        cloud_cover_filter = None
        if "max_cloud_cover" in kwargs and kwargs["max_cloud_cover"]:
            cloud_cover_filter = CloudCoverFilter(max_cc=kwargs["max_cloud_cover"])

        metadata_filter = None
        if "meta_filter" in kwargs and kwargs["meta_filter"]:
            metadata_filter = MetadataFilter.from_str(kwargs["meta_filter"])

        months = kwargs["months"] if "months" in kwargs else None

        return cls(acquisition_filter, spatial_filter, cloud_cover_filter, metadata_filter, months)
