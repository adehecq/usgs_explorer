"""
Description: module contain the unitary tests for the CLI

Last modified: 2024
Author: Luc Godin
"""
import os
from tempfile import TemporaryDirectory

import pytest
from click.testing import CliRunner

from usgsxplore.cli import cli


def test_search_no_output():
    """Test the search command with no --output"""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["search", "declassii", "--location", "23.1", "80", "--filter", "DOWNLOAD_AVAILABLE=Y"],
    )
    assert result.exit_code == 0
    assert "DZB1212-500010L002001" in result.output
    assert "DZB1212-500010L003001" in result.output


def test_search_output():
    """Test the search command with --output of any format"""
    with TemporaryDirectory() as tmpdir:
        textfile = os.path.join(tmpdir, "tmp.txt")
        jsonfile = os.path.join(tmpdir, "tmp.json")
        gpkgfile = os.path.join(tmpdir, "tmp.gpkg")
        shapefile = os.path.join(tmpdir, "tmp.shp")
        geojsonfile = os.path.join(tmpdir, "tmp.geojson")

        # execute all command
        result1 = CliRunner().invoke(cli, ["search", "declassii", "--limit", "4", "--output", textfile])
        result2 = CliRunner().invoke(cli, ["search", "declassii", "--limit", "4", "--output", jsonfile])
        result3 = CliRunner().invoke(cli, ["search", "declassii", "--limit", "4", "--output", gpkgfile])
        with pytest.warns(UserWarning):
            result4 = CliRunner().invoke(cli, ["search", "declassii", "--limit", "4", "--output", shapefile])
        result5 = CliRunner().invoke(cli, ["search", "declassii", "--limit", "4", "--output", geojsonfile])
        result6 = CliRunner().invoke(cli, ["search", "declassii", "--limit", "4", "--output", "tmp.html"])

        # assertions
        assert result1.exit_code == 0
        assert result2.exit_code == 0
        assert result3.exit_code == 0
        assert result4.exit_code == 0
        assert result5.exit_code == 0
        assert result6.exit_code == 2

        assert os.path.exists(textfile)
        assert os.path.exists(jsonfile)
        assert os.path.exists(gpkgfile)
        assert os.path.exists(shapefile)
        assert os.path.exists(geojsonfile)


def test_download():
    """Test the download command"""
    with TemporaryDirectory() as tmpdir:
        ids_file = os.path.join(tmpdir, "ids.txt")
        with open(ids_file, "w", encoding="utf-8") as file:
            file.write("#dataset=landsat_tm_c2_l1\nLT50380372012126EDC00")

        runner = CliRunner()
        result = runner.invoke(cli, ["download", ids_file, "--output-dir", tmpdir, "--pbar", "0"])

        assert result.exit_code == 0
        assert "LT05_L1TP_038037_20120505_20200820_02_T1.tar" in os.listdir(tmpdir)


def test_info():
    """Test the info command with each subcommand: dataset, filters"""
    runner = CliRunner()

    # Test the dataset subcommand
    result = runner.invoke(cli, ["info", "dataset"])
    assert result.exit_code == 0
    assert len(result.output) == 2298  # Possibly to be updated in the future

    # Test the filters subcommand
    result = runner.invoke(cli, ["info", "filters", "declassii"])
    assert result.exit_code == 0
