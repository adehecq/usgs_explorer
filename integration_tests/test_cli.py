"""
Description: module contain the unitary tests for the CLI

Last modified: 2024
Author: Luc Godin
"""
import os
from tempfile import TemporaryDirectory

from click.testing import CliRunner

from usgsxplore.cli import cli


def test_search():
    """Test the search command"""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["search", "declassii", "--location", "23.1", "80", "--filter", "DOWNLOAD_AVAILABLE=Y"],
    )
    assert result.exit_code == 0
    assert "DZB1212-500010L002001" in result.output
    assert "DZB1212-500010L003001" in result.output


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
