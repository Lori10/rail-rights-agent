# Tasks

## 1. Project scaffold and failing tests (red by design)

- [x] 1.1 Add `pyproject.toml` with:
  - `requires-python = ">=3.12,<3.13"`
  - the src-layout package `rail_rights_agent` (empty `__init__.py`)
  - dependency groups `dev` (ruff, mypy, pytest) and `infra` (aws-cdk-lib, constructs), both in `default-groups`
  - ruff, mypy (strict, per-module relaxation for tests) and pytest config (`testpaths`, `live` marker, `addopts = "-m 'not live'"`)

  Also add `.python-version` (3.12) and `uv.lock`.

  Verify: `uv sync` succeeds and `uv run python -V` prints 3.12.x.
- [x] 1.2 Write `tests/unit/test_settings.py` covering every `project-configuration` scenario:
  - defaults
  - primary-model override
  - profile override
  - empty value names the variable
  - eu-north-1 accepted
  - us-east-1 rejected, naming eu-north-1
  - frozen assignment raises

  Verify: the tests fail (the settings module doesn't exist yet).
- [x] 1.3 Write `tests/unit/test_no_hardcoded_model_ids.py`, the source scan from D9. Verify: it fails until the settings module exists, or passes trivially. Either way, record which.
- [x] 1.4 Write `tests/infra/test_app.py` covering every testable `infrastructure-baseline` scenario:
  - all stacks in eu-north-1
  - probe resource carries the four tags
  - every taggable resource in every stack carries the tags
  - synthesis succeeds with all `AWS_*` and `CDK_DEFAULT_*` env vars removed
  - budget present with the 3 notifications when an email is set
  - no budget when it is unset

  Uses one module-scoped synth fixture. Verify: the tests fail (no `infra` package yet).
- [x] 1.5 Write `tests/unit/test_quality_config.py` asserting that the `live` marker is registered and the default `addopts` excludes it. Add a sample `@pytest.mark.live` test that would fail if run. Verify: `uv run pytest -q` deselects it, and `uv run pytest -q -m live` selects it.
- [x] 1.6 Commit the group (`test: failing tests for foundation`). Verify: `uv run pytest -q` shows the expected failures, with no collection errors other than missing modules.

## 2. Configuration

- [x] 2.1 Implement `src/rail_rights_agent/settings.py`: the frozen `Settings` dataclass and `load_settings(env)` per D3, including the optional budget email and limit. Verify: `tests/unit/test_settings.py` and the model-id scan pass.
- [x] 2.2 Add `.env.example` documenting every `RAILAGENT_*` variable with its default, and no real values. Verify: each variable read in `settings.py` appears in `.env.example` (checked by an extra assertion in `test_settings.py`).
- [x] 2.3 Commit (`feat: typed settings with eu-north-1 region lock`).

## 3. CDK app skeleton

- [x] 3.1 Implement `infra/tagging.py` (`apply_project_tags`), `infra/stacks/baseline.py` (empty `BaselineStack`), `infra/stacks/budget.py` (`BudgetStack`, per D7) and `infra/app.py` (`build_app(settings)` plus `main`, per D4/D5). Verify: `tests/infra/test_app.py` passes.
- [x] 3.2 Add `cdk.json` (app `uv run python -m infra.app`) and `infra/env.py`, which prints profile and region from settings. Verify: `npx --yes aws-cdk@2.1147.0 synth --quiet` succeeds locally with no credentials, and `cdk.out/` is gitignored.
- [x] 3.3 Add `scripts/_cdk.sh` (pinned CLI version), `scripts/deploy.sh` and `scripts/destroy.sh`, per D6. Verify: `bash -n` passes on all three, and `scripts/deploy.sh --help`, or a dry `synth` path, prints the profile and region it would use, without calling AWS.
- [x] 3.4 Commit (`feat: CDK app skeleton with project tags and opt-in budget`).

## 4. Quality gates and docs

- [x] 4.1 Add the `ruff format --check .` and `mypy` gates to `scripts/check.sh`, per D8. Verify by hand:
  - a deliberate type error in a scratch edit makes `scripts/check.sh` report FAIL on the type gate
  - a deliberate misformat fails the format gate

  Revert both, then confirm `scripts/check.sh` exits 0.
- [x] 4.2 Confirm CI needs no workflow change. Push the branch and open a draft PR (`gh pr create --draft`, body linking `openspec/changes/foundation/`). Verify: the `checks` job is green. If it isn't, fix `ci.yml` minimally and record why in design.md.
- [x] 4.3 Add a short "Development" section to the README covering `uv sync`, `scripts/check.sh`, the configuration variables, and deploy/destroy. Create the README if it doesn't exist; `portfolio-docs` will expand it. Verify: every command in it runs as written offline, except deploy/destroy.
- [x] 4.4 Run `/devflow:verify` and confirm PASS. Record any known gaps in design.md under Risks / Trade-offs.

## 5. Budget via Budgets API custom resource (found in live check 6.3)

- [ ] 5.1 Revise the budget tests in `tests/infra/test_app.py`. They should assert one `Custom::AWS` resource whose Create call is `Budgets:CreateBudget` with:
  - a monthly COST budget ($20 default)
  - the three notifications to the configured address
  - the four project `ResourceTags`
  - the hashed name

  Also assert that Delete is `Budgets:DeleteBudget`, and that there is no budget custom resource when the email is unset. The user approved this test edit (the design changed, not the spec). Verify: the tests fail against the current `CfnBudget` stack. Commit (`test: assert budget via Budgets API custom resource`).
- [ ] 5.2 Reimplement `infra/stacks/budget.py` with `AwsCustomResource`, per D7 (least-privilege policy; managed log group with 1-week retention, destroyed on delete). Verify: `tests/infra/test_app.py` passes. Commit.
- [ ] 5.3 Run `/devflow:verify` and confirm PASS.

## 6. Live checks (user runs or approves; each step needs explicit go-ahead)

- [x] 6.1 With fresh `railagent` credentials, run `scripts/deploy.sh` (no budget email). Verify: `RailRightsAgent-Baseline` exists in eu-north-1 with the four stack tags (`aws cloudformation describe-stacks`). Cost: $0.
- [x] 6.2 Run `scripts/destroy.sh`. Verify: the stack is gone. Cost: $0.
- [ ] 6.3 Set `RAILAGENT_BUDGET_EMAIL` locally and run `scripts/deploy.sh`. Verify: `aws budgets describe-budgets` shows the budget with a $20 limit, `describe-notifications-for-budget` shows the three notifications, and the confirmation email arrives. The budget stays deployed. Cost: about $0.

## Workflow follow-up

- `/opsx:archive foundation` on the branch, then `/devflow:land-branch`.
- Run `scripts/setup_github.sh` once after the first push, if the ruleset isn't set up yet.
