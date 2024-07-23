# pylint: disable=protected-access
# pylint: disable=wrong-import-position
"""
Description: module contain the unitary tests for classes: API, ScenesDownloader, all filter classes

Last modified: 2024
Author: Luc Godin
"""

import os
from tempfile import TemporaryDirectory

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

import usgsxplore.errors as err
import usgsxplore.filter as filt
from usgsxplore.api import API
from usgsxplore.scenes_downloader import Product, ScenesDownloader


class TestAPI:
    """
    This class test the API class
    """

    @classmethod
    def setup_class(cls):
        cls.api = API(os.getenv("USGSXPLORE_USERNAME"), token=os.getenv("USGSXPLORE_TOKEN"))

    @classmethod
    def teardown_class(cls):
        cls.api.logout()

    def test_login(self):
        "Test the login to the api"
        assert self.api.session.headers.get("X-Auth-Token")

    def test_login_error(self):
        "Test the error of the login"
        with pytest.raises(err.USGSAuthenticationError):
            API("bad_username", token="bad_token")

    def test_get_scene_id(self):
        "Test the convert of display_id to entity_id"
        # Single Product ID
        display_id = "LT05_L1TP_038037_20120505_20200820_02_T1"
        entity_id = self.api.get_entity_id(display_id, dataset="landsat_tm_c2_l1")
        assert entity_id == "LT50380372012126EDC00"

        # Multiple Product IDs
        product_ids = [
            "LT05_L1TP_038037_20120505_20200820_02_T1",
            "LT05_L1TP_031033_20120504_20200820_02_T1",
        ]
        scene_ids = self.api.get_entity_id(product_ids, dataset="landsat_tm_c2_l1")
        assert scene_ids == ["LT50380372012126EDC00", "LT50310332012125EDC00"]

    def test_get_entity_id(self):
        "Test the convert of entity id to display id"
        entity_id = "LT50380372012126EDC00"
        display_id = self.api.get_display_id(entity_id, dataset="landsat_tm_c2_l1")
        assert display_id == "LT05_L1TP_038037_20120505_20200820_02_T1"

    def test_scene_search(self):
        "Test the scene search method"
        result = self.api.scene_search("landsat_tm_c2_l1", max_results=1, metadata_type=None)

        assert result["recordsReturned"] == 1
        assert result["totalHits"] == 2940421
        assert result["startingNumber"] == 1
        assert result["results"][0]["metadata"] == []

    def test_batch_search(self):
        "Test the batch search method"
        scenes_count = [30, 30, 30, 10]
        i = 0

        for scenes_batch in self.api.batch_search(
            "declassii", max_results=100, metadata_type=None, batch_size=30, use_tqdm=False
        ):
            assert len(scenes_batch) == scenes_count[i]
            i += 1

    def test_search(self):
        "Test the search method"
        scenes = self.api.search("declassii", location=(2.2, 46.23), meta_filter="camera=L")
        assert len(scenes) == 19

        scenes = self.api.search(
            "landsat_tm_c2_l1", bbox=(5.7074, 45.1611, 5.7653, 45.2065), date_interval=("2010-01-01", "2019-12-31")
        )
        assert len(scenes) == 27


class TestScenesDownloader:
    """
    This class test the ScenesDownloader class, it need an open API instance
    """

    testing_df = pd.DataFrame(
        {
            "product_id": ["pi_1", "pi_2", "pi_3", None],
            "display_id": ["di_1", "di_2", "di_3", None],
            "filesize": [100, 200, 0, None],
            "url": ["url_1", None, None, None],
            "progress": [70, 0, 0, 0],
            "file_path": ["", None, None, None],
        },
        index=["ei_1", "ei_2", "ei_3", "ei_4"],
    )

    @classmethod
    def setup_class(cls):
        cls.api = API(os.getenv("USGSXPLORE_USERNAME"), token=os.getenv("USGSXPLORE_TOKEN"))

    @classmethod
    def teardown_class(cls):
        cls.api.logout()

    def test_set_download_options_1(self) -> None:
        """
        Test the method ScenesDownloader.set_download_options with the declassi dataset
        """
        expected_res = {
            "DZB1216-500525L001001": Product.STATE_NO_LINK,
            "DZB1216-500525L008001": Product.STATE_NO_LINK,
            "DZB1216-500523L001001": Product.STATE_UNAVAILABLE,
            "DZB1216-500523L002001": Product.STATE_UNAVAILABLE,
            "unexist_id_1": Product.STATE_UNEXIST,
            "unexist_id_2": Product.STATE_UNEXIST,
            "DZB1216-500521L001001": Product.STATE_ALREADY_DL,
        }
        entity_ids = list(expected_res.keys())

        with TemporaryDirectory() as tmp_dir:
            scenes_downloader = ScenesDownloader(entity_ids, tmp_dir, pbar_type=0)

            # create a tgz file to simulate an existing downloading
            with open(os.path.join(tmp_dir, "DZB1216-500521L001001.tgz"), mode="w", encoding="utf-8"):
                pass

            # do a download-options request and give the result to the ScenesDownloader instance
            download_options = self.api.request(
                "download-options", {"datasetName": "declassii", "entityIds": entity_ids}
            )
            scenes_downloader.set_download_options(download_options)

            # align series to compare it
            s1, s2 = scenes_downloader.get_states().align(pd.Series(expected_res))
            # test if the scenes states correspond to the expected_res
            assert sum(s1 == s2) == 7

    def test_set_download_options_2(self) -> None:
        """
        Test the method ScenesDownloader.set_download_options with a landsat dataset
        """
        expected_res = {
            "LT50380372012126EDC00": Product.STATE_NO_LINK,
            "LT50310332012125EDC00": Product.STATE_NO_LINK,
            "unexist_id_1": Product.STATE_UNEXIST,
            "unexist_id_2": Product.STATE_UNEXIST,
            "LT50310342012125EDC00": Product.STATE_ALREADY_DL,
        }
        entity_ids = list(expected_res.keys())

        with TemporaryDirectory() as tmp_dir:
            scenes_downloader = ScenesDownloader(entity_ids, tmp_dir, pbar_type=0)

            # create a tgz file to simulate an existing downloading
            with open(
                os.path.join(tmp_dir, "LT05_L1TP_031034_20120504_20200820_02_T1.tar"), mode="w", encoding="utf-8"
            ):
                pass

            # do a download-options request and give the result to the ScenesDownloader instance
            download_options = self.api.request(
                "download-options", {"datasetName": "landsat_tm_c2_l1", "entityIds": entity_ids}
            )
            scenes_downloader.set_download_options(download_options)

            # align series to compare it
            s1, s2 = scenes_downloader.get_states().align(pd.Series(expected_res))
            # test if the scenes states correspond to the expected_res
            assert sum(s1 == s2) == 5

    def test_pbar_0(self) -> None:
        "Test the progress bar with the pbar_type == 0"
        sd = ScenesDownloader(self.testing_df.index.to_list(), "", pbar_type=0, overwrite=True)
        sd.df = self.testing_df
        sd._init_pbar()
        assert sd._progress.static_pbar is None
        assert sd._progress.pbars is None

    def test_pbar_1(self) -> None:
        "Test the progress bar with the pbar_type == 1"
        sd = ScenesDownloader(self.testing_df.index.to_list(), "", pbar_type=1, overwrite=True)
        sd.df = self.testing_df.copy()
        sd._init_pbar()
        assert sd._progress.pbars is None
        assert sd._progress.static_pbar.total == 300
        assert sd._progress.static_pbar.desc == "Downloading 0/2: "

        # simulate a finishing download
        sd.df.loc["ei_1", "progress"] = sd.df.loc["ei_1", "filesize"]
        sd._update_pbar()
        assert sd._progress.static_pbar.desc == "Downloading 1/2: "

    def test_pbar_2(self) -> None:
        "Test the progress bar with the pbar_type == 2"
        sd = ScenesDownloader(self.testing_df.index.to_list(), "", pbar_type=2, overwrite=True)
        sd.df = self.testing_df.copy()
        sd._init_pbar()
        assert sd._progress.static_pbar is None
        assert sd._progress.pbars["ei_1"].total == sd.df.loc["ei_1", "filesize"]
        assert sd._progress.pbars["ei_2"].total == sd.df.loc["ei_2", "filesize"]

        assert sd._progress.pbars["ei_1"].desc == "ei_1-(downloading): "
        assert sd._progress.pbars["ei_2"].desc == "ei_2-(no link): "

        # simulate a finishing download
        sd.df.loc["ei_1", "progress"] = sd.df.loc["ei_1", "filesize"]
        sd._update_pbar()
        assert sd._progress.pbars["ei_1"].desc == "ei_1-(downloaded): "


class TestFilter:
    """
    This class test all class uses to create the SceneFilter
    """

    @classmethod
    def setup_class(cls):
        cls.api = API(os.getenv("USGSXPLORE_USERNAME"), token=os.getenv("USGSXPLORE_TOKEN"))
        cls.dataset_filters = cls.api.dataset_filters("declassii")

    @classmethod
    def teardown_class(cls):
        cls.api.logout()

    def test_coordinate(self):
        "Test the coordinate class"
        lon, lat = 17.5, 18.0
        coord = filt.Coordinate(lon, lat)
        assert coord["longitude"] == lon
        assert coord["latitude"] == lat

    def test_geojson(self):
        "Test the geojson class"
        shape = {
            "type": "Polygon",
            "coordinates": [
                [
                    [-87.90681, 41.972731],
                    [-87.629799, 41.972731],
                    [-87.629799, 42.000907],
                    [-87.90681, 42.000907],
                    [-87.90681, 41.972731],
                ]
            ],
        }
        geojson = filt.GeoJson(shape)
        assert geojson["type"] == "Polygon"
        assert isinstance(geojson["coordinates"], list)
        assert isinstance(geojson["coordinates"][0], filt.Coordinate)

    def test_spatial_filter_geojson(self):
        "Test the SpatialFilterGeoJSON class"
        shape = {
            "type": "Polygon",
            "coordinates": [
                [
                    [-87.90681, 41.972731],
                    [-87.629799, 41.972731],
                    [-87.629799, 42.000907],
                    [-87.90681, 42.000907],
                    [-87.90681, 41.972731],
                ]
            ],
        }
        sfg = filt.SpatialFilterGeoJSON(shape)
        assert sfg["filterType"] == "geoJson"
        assert isinstance(sfg["geoJson"], filt.GeoJson)

    def test_spatial_filter_from_file(self):
        "Test the SpatialFilterGeoJSON.from_file method"
        coords = [
            [-87.90681, 41.972731],
            [-87.629799, 41.972731],
            [-87.629799, 42.000907],
            [-87.90681, 42.000907],
            [-87.90681, 41.972731],
        ]
        poly = Polygon(coords)
        geometry = gpd.GeoSeries([poly], crs="EPSG:4326")
        gdf = gpd.GeoDataFrame({"geometry": geometry})
        with TemporaryDirectory() as tmp_dir:
            gdf.to_file(os.path.join(tmp_dir, "shape.geojson"), driver="GeoJSON")
            sfg = filt.SpatialFilterGeoJSON.from_file(os.path.join(tmp_dir, "shape.geojson"))
            assert sfg["filterType"] == "geoJson"
            assert isinstance(sfg["geoJson"], filt.GeoJson)

    def test_spatial_filter_mbr(self):
        "Test the SpatialFilterMbr class"
        xmin, ymin, xmax, ymax = 1, 2, 3, 4
        sfm = filt.SpatialFilterMbr(xmin, ymin, xmax, ymax)
        assert sfm["filterType"] == "mbr"
        assert sfm["lowerLeft"] == filt.Coordinate(xmin, ymin)
        assert sfm["upperRight"] == filt.Coordinate(xmax, ymax)

    def test_acquisition_filter(self):
        "Test the AcquisitionFilter class"
        start, end = "2010-01-01", "2010-01-31"
        af = filt.AcquisitionFilter(start, end)
        assert af["start"] == start and af["end"] == end

        with pytest.raises(err.AcquisitionFilterError):
            filt.AcquisitionFilter("20/11/2002", "20/11/2003")

    def test_cloud_cover_filter(self):
        "Test the CloudCoverFilter class"
        ccf = filt.CloudCoverFilter(10, 50, True)
        assert ccf["min"] == 10
        assert ccf["max"] == 50
        assert ccf["includeUnknown"]

    def test_metadata_value(self):
        # tests for all valid filters
        fields = ["5e839ff8388465fa", "Camera Resolution", "camera_resol"]
        values = ["6", "2 to 4 feet"]
        expected_f = {"filterType": "value", "filterId": "5e839ff8388465fa", "value": "6", "operand": "like"}
        for field in fields:
            for value in values:
                f = filt.MetadataValue(field, value)
                f.compile(self.dataset_filters)
                assert f == expected_f

        # test for all non-valid filters
        with pytest.raises(err.FilterFieldError):
            f = filt.MetadataValue("unknown_field", "unknown_value")
            f.compile(self.dataset_filters)

        with pytest.raises(err.FilterValueError):
            f = filt.MetadataValue("5e839ff8388465fa", "unknown_value")
            f.compile(self.dataset_filters)

    def test_metadata_and(self):
        "Test the __and__ method with 2 filter"

        # Test a and between two MetadataValue filter
        filter1 = filt.MetadataValue("camera_resol", "6") & filt.MetadataValue("camera", "H")
        expected_f = {
            "filterType": "and",
            "childFilters": [
                {"filterType": "value", "filterId": "5e839ff8388465fa", "value": "6", "operand": "like"},
                {"filterType": "value", "filterId": "5e839ff8cfa94807", "value": "H", "operand": "like"},
            ],
        }

        filter1.compile(self.dataset_filters)
        assert filter1 == expected_f

        # Test a triple and
        filter2 = filter1 & filt.MetadataValue("DOWNLOAD_AVAILABLE", "Yes")
        expected_f = {
            "filterType": "and",
            "childFilters": [
                {
                    "filterType": "and",
                    "childFilters": [
                        {"filterType": "value", "filterId": "5e839ff8388465fa", "value": "6", "operand": "like"},
                        {"filterType": "value", "filterId": "5e839ff8cfa94807", "value": "H", "operand": "like"},
                    ],
                },
                {"filterType": "value", "filterId": "5e839ff8ba6eead0", "value": "Y", "operand": "like"},
            ],
        }
        filter2.compile(self.dataset_filters)
        assert filter2 == expected_f

    def test_metadata_or(self):
        "Test the __or__ method"
        f = filt.MetadataValue("camera_resol", "6") | filt.MetadataValue("camera", "H")
        f = f | filt.MetadataValue("DOWNLOAD_AVAILABLE", "Yes")

        expected_f = {
            "filterType": "or",
            "childFilters": [
                {
                    "filterType": "or",
                    "childFilters": [
                        {"filterType": "value", "filterId": "5e839ff8388465fa", "value": "6", "operand": "like"},
                        {"filterType": "value", "filterId": "5e839ff8cfa94807", "value": "H", "operand": "like"},
                    ],
                },
                {"filterType": "value", "filterId": "5e839ff8ba6eead0", "value": "Y", "operand": "like"},
            ],
        }

        f.compile(self.dataset_filters)

        assert f == expected_f

    def test_metadata_filter_from_str(self):
        "Test the from_str constructor for MetadataFilter"
        str_repr = "camera_resol=6 & camera='H' | 'Download Available' = Yes"
        f = filt.MetadataFilter.from_str(str_repr)
        expected_f = {
            "filterType": "and",
            "childFilters": [
                {"filterType": "value", "filterId": "5e839ff8388465fa", "value": "6", "operand": "like"},
                {
                    "filterType": "or",
                    "childFilters": [
                        {"filterType": "value", "filterId": "5e839ff8cfa94807", "value": "H", "operand": "like"},
                        {"filterType": "value", "filterId": "5e839ff8ba6eead0", "value": "Y", "operand": "like"},
                    ],
                },
            ],
        }
        f.compile(self.dataset_filters)
        assert f == expected_f

        # test Error
        with pytest.raises(err.FilterMetadataValueError):
            filt.MetadataFilter.from_str("not_valid repr")

    def test_scene_filter(self):
        "Test the scene_filter"
        sf = filt.SceneFilter.from_args(location=(18, 18), months=[1, 2, 3])
        assert isinstance(sf["spatialFilter"], filt.SpatialFilterMbr)
        assert sf["seasonalFilter"] == [1, 2, 3]

        sf = filt.SceneFilter.from_args(date_interval=("2020-05-25", "2021-05-25"), max_cloud_cover=70)
        assert isinstance(sf["acquisitionFilter"], filt.AcquisitionFilter)
        assert isinstance(sf["cloudCoverFilter"], filt.CloudCoverFilter)

        sf = filt.SceneFilter.from_args(meta_filter="field=value")
        assert isinstance(sf["metadataFilter"], filt.MetadataFilter)


# End-of-file (EOF)
