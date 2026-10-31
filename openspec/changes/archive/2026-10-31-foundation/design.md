# Design

## Context

The scaffold already has:
- `.github/workflows/ci.yml`: one `checks` job that runs `uv sync --frozen`, then gitleaks, then `scripts/check.sh`. Node 20 is installed for the pinned OpenSpec CLI.
- `scripts/check.sh`: ruff, pytest, `openspec validate --strict`, gitleaks and the weakened-test scan.
- `.claude/devflow.env`: declares `src tests infra pyproject.toml` as code paths.

There is no `pyproject.toml` or lockfile yet, so CI cannot pass until this change adds them.

The AWS account is on the free plan ($100 credit until 2027-04-28), and a RegionFloor SCP limits it to eu-north-1. CDK is already bootstrapped there. Requirements are in `specs/`; motivation is in `proposal.md`.

## Goals / Non-Goals

**Goals:**
- Later changes add stacks and modules without touching the scaffolding again.
- The offline suite, including CDK synthesis, runs in seconds without credentials, both locally and in CI.

**Non-Goals:**
- Any application behaviour: agent, tools, KB.
- GitHub OIDC or AWS credentials in CI. That arrives with `evaluation`, if at all.
- Multiple environments (dev/prod). `environment=dev` is the only value for now.
- Containerisation, which arrives with `agentcore`.

## Decisions

### D1. Layout: `src/rail_rights_agent/`, `infra/`, `tests/`
- **Choice:**
  - `src/rail_rights_agent/`: an installable package (src layout).
  - `infra/`: a separate top-level package holding the CDK app (`infra/app.py`) and stacks (`infra/stacks/`).
  - `tests/`: mirrors both (`tests/unit/`, `tests/infra/`).

  Infra imports settings from `rail_rights_agent.settings`, so there is one source of configuration.
- **Why:** Matches `DEVFLOW_CODE_PATHS`. Keeps CDK, a heavy dependency, out of the runtime package, so Lambda and Runtime artifacts later don't pull it in.
- **Rejected:** infra inside `src/rail_rights_agent/`, which couples the deploy tool to the runtime package. A separate `infra/pyproject.toml`, which means two lockfiles and two environments for little gain.

### D2. Dependencies grouped, not runtime
- **Choice:**
  - `[dependency-groups]` `dev` = `ruff`, `mypy`, `pytest`.
  - `infra` = `aws-cdk-lib`, `constructs`.
  - `uv sync` installs both by default (`default-groups`), which CI's `uv sync --frozen` relies on.
  - No `[project.dependencies]` yet.
  - Versions are floored at the current releases (ruff 0.17, mypy 2.4, pytest 9.2, aws-cdk-lib 2.275, constructs 10.8) and locked in `uv.lock`. Dependabot already watches uv.
- **Rejected:** putting CDK in a runtime dependency. A `requirements.txt` workflow: uv is mandated.

### D3. Settings: stdlib frozen dataclass, not pydantic-settings
- **Choice:** `Settings` is a `@dataclass(frozen=True)` with a `load_settings(env: Mapping[str, str] = os.environ)` function. That function applies defaults, strips values, rejects empty values with the variable name, and enforces `region == "eu-north-1"`. Variables:
  - `RAILAGENT_PRIMARY_MODEL_ID`
  - `RAILAGENT_COMPARISON_MODEL_ID`
  - `RAILAGENT_EMBEDDING_MODEL_ID`
  - `RAILAGENT_AWS_REGION`
  - `RAILAGENT_AWS_PROFILE`
  - `RAILAGENT_BUDGET_EMAIL` (optional)
  - `RAILAGENT_BUDGET_LIMIT_USD` (optional, default 20)

  The env mapping is injected, so tests never mutate `os.environ`. `.env.example` documents each variable.
- **Why:** Five strings and one number need no framework. It adds zero dependencies and is easy to type-check strictly.
- **Rejected:** `pydantic-settings`, which is a new dependency for trivial validation. It can be revisited if the config grows nested. Reading the standard `AWS_REGION`: the project-prefixed variable avoids silently inheriting a region set for another project. The deploy scripts pass `--profile` and the region explicitly.
- **Embedding default:** `cohere.embed-v4:0`, for multilingual DE/EN retrieval. The `knowledge-base` change owns the final choice and its justification. If it picks Titan, it modifies the `project-configuration` default requirement.

### D4. Region lock in settings, account from credentials
- **Choice:**
  - Each stack gets `env=Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=settings.aws_region)`.
  - The CDK CLI fills in `CDK_DEFAULT_ACCOUNT` from the profile at deploy time.
  - During offline synthesis and tests, the account is unset, so the stack is account-agnostic but still region-pinned.
- **Why:** No account id in source code (the repo is public), and synthesis works with no credentials.
- **Rejected:** hardcoding `750026323128`. It works, but it ties the repo to one account and leaks account metadata.

### D5. Tags via `Tags.of(app)` in one function
- **Choice:**
  - `infra/tagging.py::apply_project_tags(scope)` adds the four tags.
  - `infra/app.py::build_app(settings) -> App` builds every stack and calls the tagging function on the app.
  - The tests call `build_app`, so they test the real wiring.
  - To prove that tags reach resources, a test adds a probe resource (an SQS queue, synth only) to a stack in that app and asserts the four tags on the synthesised template.
  - A second test walks every resource in every synthesised stack that has a `Tags` property and asserts the four tags. Later changes get this check for free.
- **Rejected:** `cdk-nag`. It is useful later for security rules, but it is a new dependency, and its packs don't check custom tags. It can be reconsidered in `agentcore`.

### D6. CDK CLI pinned via `npx`, wrapped in scripts
- **Choice:**
  - `scripts/deploy.sh` runs `npx --yes aws-cdk@2.1147.0 deploy --all --profile "$profile" --require-approval never`.
  - `scripts/destroy.sh` runs `... destroy --all --force`.
  - Both read profile and region from settings, through a small `python -m infra.env` that prints them, so the settings logic isn't duplicated in bash.
  - `cdk.json` runs `uv run python -m infra.app`.
  - The CLI version is pinned in one variable at the top of a shared `scripts/_cdk.sh`.
- **Why:** Mirrors how OpenSpec is pinned. No global install, and it gives reproducible deploys.
- **Rejected:** a Makefile, which is another tool for two commands. A global `npm i -g aws-cdk`, which is unpinned.

### D7. Budget: opt-in `BudgetStack` that calls the Budgets API through a CDK custom resource, default $20/month
- **Choice:** the budget stack still exists only when `budget_email` is set. Instead of `aws_budgets.CfnBudget`, it uses `custom_resources.AwsCustomResource`:
  - **Create:** `Budgets:CreateBudget` with a monthly COST budget of `budget_limit_usd` USD; notifications ACTUAL > 50%, ACTUAL > 80% and FORECASTED > 100%, each to an EMAIL subscriber; and the four project tags as `ResourceTags`.
  - **Delete:** `Budgets:DeleteBudget`.
  - **Name:** `rail-rights-agent-monthly-<first 8 hex of sha256(email:limit)>`. The custom resource uses the name as its physical id, so changing the email or limit creates a new budget, then CloudFormation deletes the old one. No `onUpdate` logic is needed.
  - **IAM:** least privilege, `budgets:ModifyBudget`, `budgets:ViewBudget` and `budgets:TagResource` on `arn:aws:budgets::<account>:budget/<name>`.
  - **Logs:** the custom resource Lambda writes to a log group defined in the stack, with 1-week retention, removed on destroy. Otherwise Lambda would create an untagged log group that outlives the stack.
- **Why:** CloudFormation in eu-north-1 does not offer `AWS::Budgets::Budget` (`TypeNotFoundException`, found in live task 6.3 on 2026-10-31). The RegionFloor SCP blocks CloudFormation in every other region, but the Budgets API works from eu-north-1. A custom resource keeps the budget in IaC and inside one-command deploy and destroy. On the free plan, using up the credit closes the account, so early warning matters.
- **Rejected:**
  - `CfnBudget`: not available in this region.
  - A budget made in the console or with a one-off CLI call: not IaC.
  - A hand-written Lambda-backed custom resource: `AwsCustomResource` already provides the SDK call, the IAM policy and the Lambda.
  - Implementing `onUpdate`: notifications and subscribers need separate API calls each. Replacing the budget by changing its name is simpler.
  - Budget actions that auto-stop resources: too much machinery for this project.
  - Putting the budget in the baseline stack: the address would have to exist for every synthesis.
- **Cost:** the custom resource Lambda runs only at deploy and destroy, about $0. The log group holds a few KB. The first two budgets are free.
- **Trade-off:** `destroy.sh --all` removes the budget too. That is acceptable, because a destroyed system has nothing to bill.

### D8. Quality gates: extend `check.sh`, keep CI unchanged where possible
- **Choice:** Add two gates to `check.sh` after lint:
  - `uv run ruff format --check .`
  - `uv run mypy`

  mypy is configured in `pyproject.toml` with `strict = true` and `files = ["src", "infra", "tests"]`. Tests are included, but with `disallow_untyped_defs = false` for `tests.*` to avoid boilerplate annotations on test functions.

  pytest gets:
  - `addopts = "-m 'not live'"`
  - a registered `live` marker
  - `testpaths = ["tests"]`

  `.python-version` = `3.12`, so setup-uv and `uv sync` pick 3.12.

  CI needs no new steps: Node 20 is already present for the jsii runtime that CDK assertions use. `ci.yml` changes only if the first CI run proves otherwise.
- **Rejected:** a separate mypy job in CI: it would duplicate `check.sh`, which is the single gate definition. pre-commit: the devflow hooks already lint after edits.

### D9. Model-id hardcoding check is a test
- **Choice:** `tests/unit/test_no_hardcoded_model_ids.py` scans `src/` and `infra/` for the id patterns in the spec, allowing only `src/rail_rights_agent/settings.py`.
- **Why:** It enforces the spec cheaply and needs no custom lint plugin.

## Risks / Trade-offs

- **CDK synthesis in pytest is slow.** jsii starts a Node process, adding about 3–6 s. → One module-scoped fixture synthesises the app once per test module.
- **CDK assertions need Node at test time.** Locally there is Node 24; in CI, Node 20. jsii supports both. → If jsii warns about an untested Node version, set `JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1` in the pytest config, not in CI only.
- **CLI version drift.** The pinned `aws-cdk` CLI must be at least as new as the cloud assembly schema of `aws-cdk-lib`. → Pin both at the current releases. Dependabot bumps the library; the CLI pin is bumped manually. A synth-time schema error is loud.
- **Local Python is 3.11.** uv downloads 3.12 on the first `uv sync` because of `.python-version` and `requires-python = ">=3.12,<3.13"`.
- **The custom resource Lambda calls a global API (Budgets) from eu-north-1.** The CLI `describe-budgets` from eu-north-1 succeeded, so the SCP does not block it. → Live task 6.3 verifies it end to end.
- **Budget tags are set by an API call, not by CloudFormation,** so the resource-walking tag test cannot see them. → The budget test asserts the four `ResourceTags` in the create call directly.
- **Memory on the dev machine.** The host has 5.8 GB RAM. Under the WSL default (2.9 GB, 1 GB swap), the jsii Node process during CDK synth and mypy over aws-cdk-lib were OOM-killed (exit 137). → `.wslconfig` was raised to 4 GB RAM and 8 GB swap. This is environment-only; nothing in the repo changed for it.
- **First mypy run is slow.** Without a cache it took 12.7 min and 2.8 GB locally, mostly analysing aws-cdk-lib. A cached run takes about 3 s. CI starts without a cache, but on the GitHub runner the whole `checks` job took 71 s (first run, 2026-10-31), so no CI cache was added. The slowness is local and memory-bound. → Revisit only if the CI job time grows.
- **Known gaps found during testing:**
  - An empty `RAILAGENT_BUDGET_EMAIL` counts as unset (no budget) rather than an error. The empty-value rule applies to the required values only, so `.env.example` can carry the blank line.
  - `scripts/weakened_tests.py`, which the devflow template manages, is excluded from ruff, because it exceeds this repo's 100-character line length.
  - `readme` was left out of `pyproject.toml` until task 4.3 created the README (hatchling fails on a missing readme). It was restored in 4.3.
  - The project `.claude/settings.json` deny rule `Read(./.env.*)` also blocked writing `.env.example`. The user narrowed it to the explicit real env-file names.
  - Live task 6.3 (2026-10-31): the budget `rail-rights-agent-monthly-45b539ab` was created through the custom resource. Checked with the API: $20 COST monthly; ACTUAL 50/80 and FORECASTED 100 notifications to the configured email; all four tags. The task's "confirmation email arrives" check does not apply, because Budgets email subscribers need no opt-in, so the first mail is a real alert.

## Migration Plan

- This is a greenfield change. Nothing in AWS changes until the live group.
- Live group:
  1. `scripts/deploy.sh` (baseline only, no budget email), then check the stack and tags in CloudFormation.
  2. `scripts/destroy.sh`, then check the stack is gone.
  3. Optionally, set `RAILAGENT_BUDGET_EMAIL` and deploy. The budget stack creates the budget through the Budgets API and stays deployed.
- **Rollback:** `scripts/destroy.sh`.

## Open Questions

- The budget limit: $20 is the default and can be changed with `RAILAGENT_BUDGET_LIMIT_USD` without touching the spec.
