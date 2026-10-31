"""Spec: quality-gates / Offline gates never call live or billed services."""

import shlex
import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def pytest_config() -> dict[str, object]:
    config: dict[str, object] = tomllib.loads(PYPROJECT.read_text())["tool"]["pytest"][
        "ini_options"
    ]
    return config


def test_live_marker_is_registered():
    markers = pytest_config()["markers"]
    assert isinstance(markers, list)
    assert any(m.split(":")[0].strip() == "live" for m in markers)


def test_default_run_excludes_live_tests():
    addopts = pytest_config()["addopts"]
    assert isinstance(addopts, str)
    args = shlex.split(addopts)
    assert args[args.index("-m") + 1] == "not live"


@pytest.mark.live
def test_live_tests_are_deselected_by_default():
    pytest.fail("live tests must not run in the default test run")
