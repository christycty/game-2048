import os

import pytest

# The imported app is built at import time. Dev and prod export traces; tests
# and CI keep the collector off. The API image in CI sets this same variable.
os.environ["EXPORT_TRACES"] = "false"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="run tests that call a local Ollama model",
    )
    parser.addoption(
        "--load",
        action="store_true",
        default=False,
        help="run opt-in load/soak tests (fake LLM; not required PR CI)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not config.getoption("--e2e"):
        skip_e2e = pytest.mark.skip(reason="needs Ollama; run pytest --e2e")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_e2e)
    if not config.getoption("--load"):
        skip_load = pytest.mark.skip(reason="opt-in load; run pytest --load")
        for item in items:
            if "load" in item.keywords:
                item.add_marker(skip_load)
