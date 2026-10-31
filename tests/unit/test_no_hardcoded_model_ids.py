"""Spec: project-configuration / Model ids are not hardcoded outside the configuration."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = [REPO_ROOT / "src", REPO_ROOT / "infra"]
ALLOWED = {REPO_ROOT / "src" / "rail_rights_agent" / "settings.py"}
MODEL_ID = re.compile(r"anthropic\.|amazon\.nova|cohere\.embed|amazon\.titan-embed")


def test_settings_module_holds_the_model_ids():
    (allowed,) = ALLOWED
    assert MODEL_ID.search(allowed.read_text())


def test_model_ids_appear_only_in_settings():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{n}"
        for d in SCANNED_DIRS
        for path in sorted(d.rglob("*.py"))
        if path not in ALLOWED
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if MODEL_ID.search(line)
    ]
    assert offenders == []
