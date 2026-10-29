I'm starting a portfolio project with the devflow workflow (OpenSpec, spec-driven, tests first).
The repo is already scaffolded: CLAUDE.md holds the constraints (AWS environment, models, fixed
stack, design rules), openspec/config.yaml the artifact rules, CONTRIBUTING.md the change loop.
Read those first. No application code yet.

Your first job: propose a roadmap of OpenSpec changes, one per milestone below, as a list
(name, scope, what it depends on, live/billed resources it touches and their expected cost).
Don't create the changes yet; I'll review first. Then we start with `foundation` via
/devflow:new-branch and /opsx:propose.

## Purpose

Portfolio project that demonstrates production-grade AWS Bedrock + AgentCore engineering for
AI Engineer roles. Quality signals matter more than features: IaC, evaluation gated in CI,
guardrails measured with a red-team set, cost reporting, a clean README with an architecture
diagram.

## Milestones (each = one OpenSpec change)

1. foundation: repo layout, uv, ruff/mypy/pytest, CDK app skeleton, config (model ids configurable), CI lint + test
2. knowledge-base: S3 bucket for docs/source, KB with S3 Vectors, ingestion, retrieval smoke test (DE + EN)
3. tools: DynamoDB tables (mock trips/delays, claims) + seed data, Lambdas get_train_delay, calculate_compensation, submit_claim; thorough unit tests for the compensation rules
4. agent-local: Strands agent using KB retrieval + tools, confirmation flow, runs locally
5. agentcore: deploy to AgentCore Runtime, Gateway (MCP), Cognito, Memory (returning passengers, past claims)
6. guardrails: Bedrock Guardrails (PII masking for names, IBAN, booking numbers; denied topics; prompt-attack filter) + red-team test set with measured block rates
7. evaluation: golden set (~40 cases, DE + EN), metrics per model (Haiku vs Nova), CI eval gate
8. ui-observability: minimal Streamlit app, AgentCore Observability / CloudWatch traces, cost-per-conversation measurement
9. docs: README, architecture diagram, eval/cost/model-comparison tables, design note "Bedrock Agents Classic vs AgentCore + migration guide"
