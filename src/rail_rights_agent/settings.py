"""Project configuration: the one place model ids and the AWS environment come from.

Every value has a default and can be overridden by a ``RAILAGENT_*`` environment variable
(documented in ``.env.example``). The region is locked to eu-north-1: the account's SCP denies
every other region, so a different value is a mistake, not a choice.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

ALLOWED_REGION = "eu-north-1"

_DEFAULTS = {
    "RAILAGENT_PRIMARY_MODEL_ID": "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
    "RAILAGENT_COMPARISON_MODEL_ID": "eu.amazon.nova-2-lite-v1:0",
    "RAILAGENT_EMBEDDING_MODEL_ID": "cohere.embed-v4:0",
    "RAILAGENT_AWS_REGION": ALLOWED_REGION,
    "RAILAGENT_AWS_PROFILE": "railagent",
}
_DEFAULT_BUDGET_LIMIT_USD = 20


class SettingsError(ValueError):
    """Raised when the environment holds an invalid configuration value."""


@dataclass(frozen=True)
class Settings:
    primary_model_id: str
    comparison_model_id: str
    embedding_model_id: str
    aws_region: str
    aws_profile: str
    budget_email: str | None = None
    budget_limit_usd: int = _DEFAULT_BUDGET_LIMIT_USD


def _required(env: Mapping[str, str], var: str) -> str:
    value = env.get(var, _DEFAULTS[var]).strip()
    if not value:
        raise SettingsError(f"{var} is set but empty")
    return value


def _budget_limit(env: Mapping[str, str]) -> int:
    var = "RAILAGENT_BUDGET_LIMIT_USD"
    raw = env.get(var, "").strip()
    if not raw:
        return _DEFAULT_BUDGET_LIMIT_USD
    try:
        limit = int(raw)
    except ValueError:
        raise SettingsError(f"{var} must be a whole number of US dollars, got {raw!r}") from None
    if limit <= 0:
        raise SettingsError(f"{var} must be positive, got {limit}")
    return limit


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    """Build the settings from ``env`` (the process environment by default)."""
    region = _required(env, "RAILAGENT_AWS_REGION")
    if region != ALLOWED_REGION:
        raise SettingsError(
            f"RAILAGENT_AWS_REGION={region!r} is not allowed; the only allowed region is "
            f"{ALLOWED_REGION}"
        )
    return Settings(
        primary_model_id=_required(env, "RAILAGENT_PRIMARY_MODEL_ID"),
        comparison_model_id=_required(env, "RAILAGENT_COMPARISON_MODEL_ID"),
        embedding_model_id=_required(env, "RAILAGENT_EMBEDDING_MODEL_ID"),
        aws_region=region,
        aws_profile=_required(env, "RAILAGENT_AWS_PROFILE"),
        # Optional: unset or empty both mean "no budget alerts".
        budget_email=env.get("RAILAGENT_BUDGET_EMAIL", "").strip() or None,
        budget_limit_usd=_budget_limit(env),
    )
