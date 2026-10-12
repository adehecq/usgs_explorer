"""Feature tests run against the real USGS M2M API and need credentials."""

import os
from collections.abc import Callable

import pytest
from click.testing import CliRunner, Result

from usgsxplore.cli import cli


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip every test when USGS credentials are not set."""
    if os.environ.get("USGS_USERNAME") and os.environ.get("USGS_TOKEN"):
        return
    skip = pytest.mark.skip(reason="USGS_USERNAME and USGS_TOKEN must be set")
    for item in items:
        item.add_marker(skip)


@pytest.fixture(scope="session")
def invoke() -> Callable[..., Result]:
    """Run the CLI and fail with its output if it exits with an error."""

    def run(*args: str) -> Result:
        result = CliRunner().invoke(cli, args, catch_exceptions=False)
        assert result.exit_code == 0, result.output
        return result

    return run
