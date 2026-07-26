from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TRAECT_RUN_BROWSER_TESTS") == "1":
        return

    skip_browser = pytest.mark.skip(reason="browser smoke tests require TRAECT_RUN_BROWSER_TESTS=1")
    for item in items:
        if "browser" in item.keywords:
            item.add_marker(skip_browser)
