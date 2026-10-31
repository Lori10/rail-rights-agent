# Proposal

## Why

The repo has the devflow scaffolding (CI workflow, `scripts/check.sh`, OpenSpec) but no Python project, no infrastructure code and no configuration. Every later milestone (knowledge base, tools, agent, AgentCore) needs the same base: a uv project with lint, type and test gates, one place where model ids and the AWS environment are configured, and a CDK app that tags everything and only ever targets `eu-north-1`. Putting that in first keeps later changes about behaviour, not plumbing.

## What Changes

- Repo layout: `src/rail_rights_agent/` (application package), `infra/` (CDK app and stacks), `tests/` (offline tests for both).
- uv project for Python 3.12 (`pyproject.toml`, `uv.lock`, `.python-version`) with ruff (lint + format), mypy (strict) and pytest configured.
- Typed settings module: primary model id (Claude Haiku 4.5 EU inference profile), comparison model id (Nova 2 Lite EU inference profile), embedding model id, AWS region and AWS profile, all overridable by environment variables, validated at load time, with no model id hardcoded anywhere else. Any region other than `eu-north-1` is rejected.
- CDK (Python) app skeleton: `cdk.json`, an app entry point and one baseline stack. Account and region come from settings, a project tag set goes on every resource, and the CDK CLI version is pinned. Plus one-command deploy and destroy scripts.
- Optional budget stack: a monthly AWS Budget with email alerts. Only synthesised when an alert email is configured; the address is never committed.
- Quality gates: `scripts/check.sh` gains a format check and a mypy gate next to the existing ruff, pytest, OpenSpec and gitleaks gates. CI keeps running `check.sh`, which now has a lockfile to `uv sync --frozen` against.

**New dependencies (need approval):**
- Dev group: `ruff`, `mypy`, `pytest`.
- Infra group: `aws-cdk-lib`, `constructs`.
- CLI: the `aws-cdk` npm package, run pinned through `npx`, not installed globally.
- No runtime dependencies. Settings use the standard library only (see design).

**Live / billed resources:**
- None in the offline task groups. `cdk synth` and the CDK assertion tests run locally and in CI without AWS credentials.
- The final live task group, which you run or approve, has two steps:
  - A first `cdk deploy` of the baseline stack, which only contains CDK metadata, then `cdk destroy`: $0.
  - Optionally, deploying the budget stack. AWS Budgets are free for the first two budgets per account: $0.

## Capabilities

### New Capabilities
- `project-configuration`: how the application and infrastructure get model ids and the AWS environment: defaults, environment overrides, validation, and the eu-north-1 region lock.
- `infrastructure-baseline`: the CDK app contract: target account and region, mandatory tags on every resource, one-command deploy and destroy, and the optional cost-alert budget.
- `quality-gates`: the offline checks every change must pass locally and in CI (lint, format, types, tests, spec validation, secrets), and the rule that they never touch live services.

### Modified Capabilities
<!-- none: no specs exist yet -->

## Impact

- **New files:**
  - `pyproject.toml`, `uv.lock`, `.python-version`
  - `src/rail_rights_agent/__init__.py`, `src/rail_rights_agent/settings.py`
  - `infra/app.py`, `infra/stacks/`
  - `cdk.json`
  - `scripts/deploy.sh`, `scripts/destroy.sh`
  - `tests/`
  - `.env.example`
- **Modified:**
  - `scripts/check.sh`: format and mypy gates.
  - `.github/workflows/ci.yml`: only if needed for Python 3.12 or the CDK tests.
- **AWS:** no change until the live group. After it, a `RailRightsAgent-Baseline` stack in account 750026323128, eu-north-1, plus an optional budget.
