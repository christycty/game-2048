import os

import pytest

# The imported app is built at import time. Keep that process from exporting
# to a live collector. Tests that need spans pass export_traces=True.
os.environ["EXPORT_TRACES"] = "false"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="run tests that call a local Ollama model",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--e2e"):
        return
    skip = pytest.mark.skip(reason="needs Ollama; run pytest --e2e")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)
