"""Spec: project-configuration."""

import dataclasses
import re
from pathlib import Path

import pytest

from rail_rights_agent.settings import SettingsError, load_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = REPO_ROOT / "src" / "rail_rights_agent" / "settings.py"
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def test_defaults_when_no_overrides():
    s = load_settings({})
    assert s.primary_model_id == "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert s.comparison_model_id == "eu.amazon.nova-2-lite-v1:0"
    assert s.embedding_model_id == "amazon.titan-embed-text-v2:0"
    assert s.aws_region == "eu-north-1"
    assert s.aws_profile == "railagent"


def test_primary_model_override_keeps_other_defaults():
    s = load_settings({"RAILAGENT_PRIMARY_MODEL_ID": "eu.amazon.nova-2-lite-v1:0"})
    default = load_settings({})
    assert s.primary_model_id == "eu.amazon.nova-2-lite-v1:0"
    assert dataclasses.replace(s, primary_model_id=default.primary_model_id) == default


def test_profile_override():
    assert load_settings({"RAILAGENT_AWS_PROFILE": "other-profile"}).aws_profile == "other-profile"


@pytest.mark.parametrize(
    "var",
    [
        "RAILAGENT_PRIMARY_MODEL_ID",
        "RAILAGENT_COMPARISON_MODEL_ID",
        "RAILAGENT_EMBEDDING_MODEL_ID",
        "RAILAGENT_AWS_REGION",
        "RAILAGENT_AWS_PROFILE",
    ],
)
@pytest.mark.parametrize("value", ["", "   "])
def test_empty_value_rejected_naming_the_variable(var, value):
    with pytest.raises(SettingsError, match=var):
        load_settings({var: value})


def test_region_eu_north_1_accepted():
    assert load_settings({"RAILAGENT_AWS_REGION": "eu-north-1"}).aws_region == "eu-north-1"


def test_region_elsewhere_rejected_naming_allowed_region():
    with pytest.raises(SettingsError, match="eu-north-1"):
        load_settings({"RAILAGENT_AWS_REGION": "us-east-1"})


def test_loaded_settings_are_read_only():
    s = load_settings({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.primary_model_id = "something-else"  # type: ignore[misc]
    assert s.primary_model_id == "eu.anthropic.claude-haiku-4-5-20251001-v1:0"


def test_budget_unset_by_default():
    s = load_settings({})
    assert s.budget_email is None
    assert s.budget_limit_usd == 20


def test_budget_email_and_limit_from_env():
    s = load_settings(
        {"RAILAGENT_BUDGET_EMAIL": "alerts@example.com", "RAILAGENT_BUDGET_LIMIT_USD": "35"}
    )
    assert s.budget_email == "alerts@example.com"
    assert s.budget_limit_usd == 35


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_invalid_budget_limit_rejected(value):
    with pytest.raises(SettingsError, match="RAILAGENT_BUDGET_LIMIT_USD"):
        load_settings({"RAILAGENT_BUDGET_LIMIT_USD": value})


def test_every_variable_is_documented_in_env_example():
    read_vars = set(re.findall(r'"(RAILAGENT_[A-Z_]+)"', SETTINGS_FILE.read_text()))
    assert read_vars, "settings.py reads no RAILAGENT_* variables"
    documented = set(re.findall(r"^#?\s*(RAILAGENT_[A-Z_]+)=", ENV_EXAMPLE.read_text(), re.M))
    assert read_vars <= documented, f"undocumented: {sorted(read_vars - documented)}"
