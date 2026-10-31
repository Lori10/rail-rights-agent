# Roadmap

One OpenSpec change per milestone, landed in order. This file is the plan across changes; each
change's own `proposal.md` / `design.md` (under `openspec/changes/`, later `archive/`) is the
authority for its details and may refine what is written here.

**Starting a milestone:** `/devflow:new-branch` → `/opsx:propose <name>` using the entry below,
the decisions at the end, and the current `openspec/specs/`. **After landing:** set its status
here to `done` (with the archive folder) and note anything that changes later milestones.

Costs are rough estimates against the free-plan credit ($100 until 2027-04-28); each proposal
re-checks them. Design target: ~$0 idle (pay-per-use only).

| # | Change | Branch | Depends on | Status |
|---|---|---|---|---|
| 1 | `foundation` | `feat/foundation` | – | done ([archive](../openspec/changes/archive/2026-10-31-foundation/)) |
| 2 | `knowledge-base` | `feat/knowledge-base` | 1 | next |
| 3 | `tools` | `feat/tools` | 1 | planned (independent of 2) |
| 4 | `agent-local` | `feat/agent-local` | 2, 3 | planned |
| 5 | `agentcore` | `feat/agentcore` | 4 | planned |
| 6 | `guardrails` | `feat/guardrails` | 5 | planned |
| 7 | `evaluation` | `feat/evaluation` | 6 | planned |
| 8 | `ui-observability` | `feat/ui-observability` | 5 (ideally after 7) | planned |
| 9 | `portfolio-docs` | `docs/portfolio-docs` | all | planned |

## 1. foundation (done)

uv project (Python 3.12), ruff + strict mypy + pytest, typed settings (`RAILAGENT_*`, region
locked to eu-north-1), CDK app skeleton with project tags, pinned-CLI deploy/destroy scripts,
CI running `scripts/check.sh`. Specs: `project-configuration`, `infrastructure-baseline`,
`quality-gates`.

Learned / carried forward:
- CloudFormation in eu-north-1 lacks some resource types (`AWS::Budgets::Budget`). Check type
  availability (`aws cloudformation describe-type`) before designing on a CFN resource; the
  fallback is a CDK `AwsCustomResource` over the service API.
- Deployed and left running (~$0): `RailRightsAgent-Baseline` (empty) and `RailRightsAgent-Budget`
  ($20/month budget, alerts by email). Deploy with `RAILAGENT_BUDGET_EMAIL` set, or the budget
  stack is dropped from the app; `scripts/destroy.sh` removes the budget too.
- The default embedding model `cohere.embed-v4:0` is provisional; `knowledge-base` decides.
- The first mypy run over aws-cdk-lib is slow and memory-hungry locally (see README); CI is fine.

## 2. knowledge-base

S3 bucket for `docs/source/` (uploaded by CDK), S3 Vectors bucket + index, Bedrock Knowledge Base
with a data source and chunking strategy, an ingestion command, a retrieval client in `src/`,
offline tests with a stubbed client, and a live smoke test asking about 60/120-minute
compensation and Erstattung in DE and EN.
- Decide the embedding model in the design: Cohere embed v4 (multilingual DE/EN quality) vs
  Titan v2 (cheaper). Leaning Cohere. Changing the default modifies `project-configuration`.
- Verify S3 Vectors and KB APIs/CFN types against current AWS docs before designing.
- Live: S3, S3 Vectors, KB ingestion, embeddings, Retrieve. Cost: < ~$0.50 total (3 PDFs,
  a few hundred thousand tokens; storage cents/month).

## 3. tools

Pure-Python domain logic with thin Lambda handlers:
- `calculate_compensation`: deterministic, never the LLM. Art. 19 of 2021/782 (25 % from 60 min,
  50 % from 120 min) plus DB rules (€4 minimum payout, season-ticket and Deutschlandticket flat
  rates, exclusions). Table-driven and property-based tests.
- `get_train_delay` over mock trips/delays; `submit_claim` idempotent and requiring a
  confirmation token.
- Two DynamoDB tables (trips/delays, claims), on-demand, plus a seed script.
- Live: DynamoDB, Lambda. Cost: ~$0 (free tier).

## 4. agent-local

Strands agent with a bilingual system prompt; KB retrieval with citations; tools called
in-process through the same domain functions. Two-phase confirmation: show a claim summary, wait
for explicit confirmation, then call `submit_claim`. Local CLI. Offline tests with a stubbed
model assert tool-call sequences, citations present, and no `submit_claim` without confirmation.
- Live: Haiku 4.5 and Nova 2 Lite inference, KB Retrieve. Cost: ~$0.01–0.03 per conversation,
  a few dollars over development.

## 5. agentcore

AgentCore Runtime deployment via CDK; Gateway exposing the Lambdas as MCP tools; Cognito inbound
auth (machine client + test user); AgentCore Memory for returning passengers. One-command deploy
and destroy; live end-to-end test. Verify AgentCore APIs against the aws-docs MCP server first.
- Live: Runtime (pay per active vCPU/GB-hour), Gateway (per tool call), Memory (per
  event/record), Cognito (free tier), ECR/S3 for the artifact. Cost: ~$1–3 over development,
  ~$0 idle.

## 6. guardrails

Bedrock Guardrail in CDK: PII masking (built-in NAME and IBAN types, custom regex for DB booking
numbers), denied topics (e.g. court representation, non-rail topics), prompt-attack filter,
contextual grounding check if it fits. A red-team set of ~80–100 DE/EN prompts plus benign
controls, with a script reporting block rate and false-positive rate.
- Live: Guardrails (per 1k text units) + inference. Cost: < ~$1 per red-team run.

## 7. evaluation

Golden set of ~40 DE/EN cases (rights questions, compensation edge cases, claim flows). Metrics:
compensation exact match, correct tool calls, citation present and correct, refusal correctness,
latency, tokens/cost, LLM-as-judge faithfulness. Results per model (Haiku vs Nova). CI eval gate.
- Live: inference for both models + judge. Cost: ~$0.50–2 per full run.

## 8. ui-observability

Minimal local Streamlit chat (Cognito token, confirmation button; local, not hosted, so no idle
cost). AgentCore Observability: Transaction Search, GenAI dashboard, traces. Cost-per-conversation
report from token usage in traces (reuse eval token data if 7 has landed).
- Live: CloudWatch Logs, X-Ray spans, inference. Enabling Transaction Search is an account-level
  setting. Cost: < ~$1/month at this volume.

## 9. portfolio-docs

README, architecture diagram as code, eval / red-team / cost / model-comparison tables generated
from result files, and the design note "Bedrock Agents Classic vs AgentCore + migration guide".
No live resources.

## Decisions agreed for later milestones

Approved with the roadmap (2026-10-31); the relevant change's design records the details.

1. **CI eval gate (7):** the repo is public, so live evals never run on fork PRs. Every PR runs an
   offline gate against a committed results file; the live eval runs on `workflow_dispatch` or a
   label, same-repo PRs only, with AWS access through a GitHub OIDC role (a cloud write that needs
   approval).
2. **Guardrails vs `submit_claim` (6):** masking names and IBANs on input would strip the data a
   claim needs. Mask in outputs, logs and Memory; pass claim fields to the tool unmasked.
3. **Memory vs claims table (5):** DynamoDB is the single source of truth for past claims;
   AgentCore Memory holds preferences and session summaries only.
4. **Naming (9):** the docs change is `portfolio-docs`, not `docs`.
