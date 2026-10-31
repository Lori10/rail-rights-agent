# Rail Rights Agent

Bilingual (DE/EN) AI agent on AWS Bedrock AgentCore that explains rail passenger rights under EU Regulation 2021/782 and Deutsche Bahn conditions of carriage, checks train delays, computes compensation and submits a claim after explicit confirmation.

## Where things are
- `docs/ROADMAP.md`: the milestone plan across changes (order, scope, cost, status) and decisions agreed for later milestones. Start each new change from its entry; set its status to done after landing.
- `openspec/specs/<capability>/spec.md`: what the system must do. Read the relevant spec before changing a capability.
- `openspec/changes/<name>/`: open changes; each records its decisions in its own `design.md`. Archived changes keep the design history.
- `CONTRIBUTING.md`: the change loop, step by step.
- `.claude/devflow.env`: workflow config (protected branch, pinned OpenSpec version, test/lint commands).

## Constraints
<!-- Only what an agent can't infer from the code. Keep this file short and free of status
     ("X is merged but not archived"): status goes stale; `openspec list` and the session
     hook provide it. -->
- Python 3.12. Manage deps with `uv`, never pip.
- Ask before adding any dependency (enforced by a hook).
- AWS: profile `railagent`, region `eu-north-1` only. Deploy/destroy and cloud write calls need explicit approval (enforced by a hook).
  - Account 750026323128; a RegionFloor SCP denies every other region. CDK is bootstrapped in eu-north-1.
  - Credentials last 12h. On WSL, renew with `BROWSER=none aws login --profile railagent --redirect-port 53682` run in the background, then give the user the printed URL.
- Models (EU cross-region inference profiles, ids configurable): primary `eu.anthropic.claude-haiku-4-5-20251001-v1:0`, comparison `eu.amazon.nova-2-lite-v1:0`. Claude Haiku/Sonnet 5.5 are not available on this account. Embeddings: `cohere.embed-v4:0` or `amazon.titan-embed-text-v2:0` (justify the choice in the design).
- Stack is fixed (ask before substituting): uv, ruff, mypy, pytest; AWS CDK (Python) for all infrastructure, one-command deploy and destroy; Strands Agents on AgentCore Runtime; AgentCore Gateway (Lambda tools as MCP, Cognito inbound auth), Memory, Observability; Bedrock Knowledge Bases on S3 Vectors; Bedrock Guardrails; DynamoDB; Streamlit UI; GitHub Actions.
- Never OpenSearch Serverless (idle cost) and never Bedrock Agents Classic (closed to new customers). Everything tagged; no idle-cost resources.
- AgentCore and S3 Vectors are new: verify APIs against current AWS docs (aws-docs MCP server), don't guess.
- Compensation is computed deterministically in code (Art. 19 of 2021/782 and DB rules), never by the LLM; the LLM explains and cites. `submit_claim` requires explicit user confirmation. Every answer about rights cites retrieved passages.
- Source documents are in `docs/source/` (gitignored): `eu-2021-782-en.pdf`, `eu-2021-782-de.pdf`, `db-befoerderungsbedingungen-de.pdf`. Don't download others.
- Prefer simple and working over clever.

## Workflow
- Spec before code: `/devflow:new-branch` → `/opsx:propose` → user approves the artifacts → `/opsx:apply` → `/devflow:verify` → `/opsx:archive` on the branch → `/devflow:land-branch`. Don't write source until the artifacts are approved.
- Tests first: write failing tests from the change's spec scenarios, then implement. Never weaken an existing test unless its spec changed (`/devflow:verify` scans for this).
- `uv run pytest -q` is offline only. Live or billed checks are separate; the user runs or approves them.
- Run OpenSpec pinned: `npx --yes @fission-ai/openspec@1.15.0 <cmd>` (a bare `openspec` is rewritten automatically).

## Git
- Branch off an up-to-date `main` (`feat/…`, `fix/…`, `chore/…`, `docs/…`), named after the OpenSpec change.
- During `/opsx:apply`, one commit per task group (the tests-first group too: it is red by design). After the first group that passes `/devflow:verify`, push and open a draft PR (`gh pr create --draft`, body links the change folder); push after each later group.
- `main` is protected on GitHub (PR + green `checks`, no bypass). Land with `/devflow:land-branch`: merge commit only, no rebase or squash unless asked.
