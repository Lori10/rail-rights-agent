# Tasks

## 1. Dependencies and failing tests (red by design)

- [x] 1.1 With the user's approval (proposal, Impact):
  - `uv add boto3`
  - `uv add --group dev "boto3-stubs[bedrock-agent,bedrock-agent-runtime,cloudformation,s3]"`

  Verify:
  - `uv sync` succeeds and `uv.lock` is updated
  - `uv run python -c "import boto3, mypy_boto3_bedrock_agent_runtime"` succeeds
  - `uv run pytest -q` is still green
- [x] 1.2 The `project-configuration` spec changed, so update the expected embedding id in `tests/unit/test_settings.py::test_defaults_when_no_overrides` to `amazon.titan-embed-text-v2:0`. Verify: that test fails against the current default.
- [x] 1.3 Write `tests/infra/test_knowledge_base_stack.py`, one test per scenario in the spec's infrastructure requirements:
  - documents bucket: public access blocked, encryption, TLS-only policy
  - vector bucket and index: float32/1024/cosine, non-filterable `AMAZON_BEDROCK_TEXT` and `AMAZON_BEDROCK_METADATA`
  - knowledge base: S3 Vectors storage, an embedding ARN ending in the configured model id, 1024 FLOAT32
  - data source: `documents/` prefix, fixed size 300/20
  - role: trust and the three scoped statements
  - the three outputs
  - no `AWS::OpenSearchServerless::*` in any stack

  Verify: the tests fail (no stack module yet).
- [x] 1.4 Write the `tests/unit/knowledge_base/` tests, using botocore `Stubber` and a fake sleep, one test per scenario of the spec's catalogue, ingestion, stack-output, retrieval and error requirements:
  - catalogue content; a missing file means no upload and no job
  - sidecar JSON per document
  - job complete, failed, and failed-docs cases; poll timeout
  - stack outputs present / stack missing
  - passage mapping and order, optional page, empty result
  - `de` filter in the request, `fr` rejected
  - empty question, `top_k` 0/21, default 5
  - `ResourceNotFoundException` wrapped with its code

  Verify: the tests fail at import (no package yet).
- [x] 1.5 Write `tests/live/test_knowledge_base_live.py` with `@pytest.mark.live`: the four live scenarios, resolving the knowledge base from the stack outputs. Verify: `uv run pytest -q` deselects it, and `uv run pytest -q -m live --collect-only tests/live` collects 4 tests.
- [x] 1.6 Commit (`test: failing tests for knowledge base`). Verify: `uv run pytest -q` shows only the expected failures, with no collection errors other than missing modules.

## 2. Configuration default

- [ ] 2.1 Change the embedding default in `src/rail_rights_agent/settings.py` and in `.env.example` to `amazon.titan-embed-text-v2:0`. Verify: `tests/unit/test_settings.py` and `test_no_hardcoded_model_ids.py` pass.
- [ ] 2.2 Commit (`feat: default embedding model to Titan Text Embeddings V2`).

## 3. Knowledge-base stack

- [ ] 3.1 Implement `infra/stacks/knowledge_base.py` per design D1–D5 and D7: documents bucket, `CfnVectorBucket`, `CfnIndex`, service role with an explicit dependency, `CfnKnowledgeBase`, `CfnDataSource`, and the outputs. Wire it into `build_app`. Verify:
  - `tests/infra/test_knowledge_base_stack.py` passes
  - the existing `tests/infra/test_app.py` passes unchanged, including the every-resource tag walk over the new stack
- [ ] 3.2 Verify `scripts/deploy.sh --dry-run` synthesises all stacks offline with no credentials and no `docs/source/` folder (rename it temporarily).
- [ ] 3.3 Commit (`feat: knowledge base stack on S3 Vectors`).

## 4. Ingestion and retrieval

- [ ] 4.1 Implement `catalogue.py`, `errors.py` and `retrieval.py` per D6, D8 and D9. Verify: the catalogue and retrieval unit tests pass.
- [ ] 4.2 Implement `ingest.py` and `aws.py` per D5, D8 and D9. Verify: the ingestion and stack-output unit tests pass.
- [ ] 4.3 Implement `__main__.py` with the `ingest` and `retrieve` subcommands. Verify:
  - `uv run python -m rail_rights_agent.knowledge_base --help` lists both subcommands
  - `retrieve ""` exits 1 with the empty-question message and makes no AWS call (run it with no credentials)
- [ ] 4.4 Extend the README "Development" section with the ingest and retrieve commands and the deploy → ingest order. Verify: the `--help` command runs exactly as written.
- [ ] 4.5 Commit (`feat: knowledge base ingestion and retrieval client`).

## 5. Gate

- [ ] 5.1 Run `/devflow:verify` and confirm PASS. Record any known gaps under Risks / Trade-offs in design.md. After PASS, push and open the draft PR (`gh pr create --draft`, body links `openspec/changes/knowledge-base/`).

## 6. Live checks (user runs or approves; each step needs explicit go-ahead)

- [ ] 6.1 With fresh `railagent` credentials, run `scripts/deploy.sh`. Verify:
  - `RailRightsAgent-KnowledgeBase` is `CREATE_COMPLETE` in eu-north-1 with the four tags
  - its three outputs are present
  - `aws s3vectors list-indexes` shows the index

  Cost: about $0.
- [ ] 6.2 Run `uv run python -m rail_rights_agent.knowledge_base ingest`. Verify: it exits 0 with 3 scanned, 3 indexed and 0 failed documents. Cost: about $0.01.
- [ ] 6.3 Run `uv run pytest -q -m live tests/live/test_knowledge_base_live.py`. Verify: 4 passed. Record in design.md whether passages carry page numbers, and note any weak results. Cost: under $0.01.
- [ ] 6.4 Run `scripts/destroy.sh`. Verify:
  - no `RailRightsAgent-KnowledgeBase` stack remains
  - `aws s3vectors list-vector-buckets` shows no project bucket
  - the documents bucket is gone

  Record in design.md whether the auto-delete log group remains. Cost: $0.
- [ ] 6.5 Optional, your call: redeploy and re-ingest, and leave the knowledge base running for `agent-local`. Cost: about $0.01, then storage cents per month.

## Workflow follow-up

- Set roadmap entry 2 to done (with the archive folder), and note the Titan V2 decision for later milestones in `docs/ROADMAP.md`.
- `/opsx:archive knowledge-base` on the branch, then `/devflow:land-branch`.
