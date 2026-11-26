# Tasks

## 1. Dependencies and failing tests (red by design)

- [ ] 1.1 With the user's approval (proposal, Impact; design D8): `uv add --group dev hypothesis` and change the `boto3-stubs` extras to `[bedrock-agent,bedrock-agent-runtime,cloudformation,dynamodb,lambda,s3]` (`uv sync`). Verify: `uv run python -c "import hypothesis, mypy_boto3_dynamodb, mypy_boto3_lambda"` succeeds and `uv run pytest -q` is still green.
- [ ] 1.2 Add `tests/unit/conftest.py` with the offline boto3 client and `Stubber` fixtures (dummy credentials, eu-north-1) for `dynamodb`, keeping the knowledge-base conftest unchanged. Verify: `uv run pytest -q tests/unit/knowledge_base` still passes.
- [ ] 1.3 Write `tests/unit/tools/test_compensation.py`: one test per scenario of the `compensation-calculation` spec (percentage bands, return half price, rounding 29.90→7.48, €12→payout 0 and no token, €16→€4.00 with token, the five exclusions, strike and unknown cause compensable, season ticket 2nd class €5, BahnCard 100 1st class €15, season 59 min, cap €16→€4.00, Deutschland-Ticket not computable with C.3.10.3, references on an eligible result, token stable and price-sensitive, negative delay and zero price rejected) plus the Hypothesis properties. Verify: the module fails at import (no `rail_rights_agent.tools` yet).
- [ ] 1.4 Write `tests/unit/tools/test_delays.py`, `test_claims.py`, `test_seed_data.py` and `test_handlers.py` from the `train-delay-lookup`, `claim-submission` and `tool-functions` scenarios: item mapping for delayed and cancelled records, `ice 123` normalisation, not-found naming train and date, invalid date with no call, seed coverage list, seed twice uses the same keys, matching token stored with the full record, empty token and mismatched token rejected before any call, payout 0 rejected, second submission → same id and `already_submitted`, empty name rejected, handler JSON for compensation, `TRIP_NOT_FOUND` error shape, service error code passed through. Verify: all fail at import.
- [ ] 1.5 Write `tests/infra/test_tools_stack.py` from the infrastructure scenarios: two on-demand tables with the right keys and delete policy, three Python 3.12 functions with timeout ≤ 10 s, env vars and stack-owned 7-day log groups, per-function policies (trips read only, claims get/put only, none for compensation, no `*` resources), the five outputs. Verify: fails (no `RailRightsAgent-Tools` stack).
- [ ] 1.6 Write `tests/live/test_tools_live.py` (`@pytest.mark.live`) for the live round trip, resolving function ARNs from the stack outputs. Verify: `uv run pytest -q` deselects it and `uv run pytest -q -m live --collect-only tests/live` collects it.
- [ ] 1.7 Commit (`test: failing tests for delay, compensation and claim tools`). Verify: `uv run pytest -q` shows only the expected failures and no collection errors other than missing modules.

## 2. Compensation rules

- [ ] 2.1 Implement `rail_rights_agent/tools/compensation.py` per design D1 and D2 (enums, dataclasses, rules table with clause references, `calculate_compensation`, token). Verify: `tests/unit/tools/test_compensation.py` passes, Hypothesis included.
- [ ] 2.2 Commit (`feat: deterministic compensation rules from Art. 19 and DB conditions`).

## 3. Delay lookup, claims and shared AWS helpers

- [ ] 3.1 Add `rail_rights_agent/aws.py` (D7) and make `knowledge_base/aws.py` and `knowledge_base/ingest.py` import from it. Verify: `tests/unit/knowledge_base` passes unchanged.
- [ ] 3.2 Implement `tools/delays.py`, `tools/seed_data.py` and `tools/deployment.py` per D3 and D6. Verify: `test_delays.py` and `test_seed_data.py` pass.
- [ ] 3.3 Implement `tools/claims.py` per D4. Verify: `test_claims.py` passes.
- [ ] 3.4 Implement `tools/handlers.py` per D5. Verify: `test_handlers.py` passes and `uv run mypy` is clean.
- [ ] 3.5 Implement `tools/__main__.py` with `seed`, `delay TRAIN DATE` and `compensate` (offline) subcommands. Verify: `uv run python -m rail_rights_agent.tools --help` lists them and `compensate --price 100 --delay 60` prints €25.00 without any AWS call (run with no credentials).
- [ ] 3.6 Commit (`feat: train delay lookup and idempotent claim submission`).

## 4. Tools stack

- [ ] 4.1 Implement `infra/stacks/tools.py::ToolsStack` per D6 and wire it into `build_app`. Verify: `tests/infra/test_tools_stack.py` passes and `tests/infra/test_app.py` passes unchanged, including the tag walk over the new stack.
- [ ] 4.2 Verify `scripts/deploy.sh --dry-run` synthesises every stack offline with no credentials, and the tools asset zip in `cdk.out` contains `rail_rights_agent/tools/handlers.py` and no `knowledge_base/` or `__pycache__`.
- [ ] 4.3 Commit (`feat: tools stack with DynamoDB tables and Lambda functions`).

## 5. Docs and gate

- [ ] 5.1 Extend the README "Development" section with the `seed`, `delay` and `compensate` commands and the deploy → seed order. Verify: the `--help` command runs as written.
- [ ] 5.2 Update `docs/ARCHITECTURE.md`: status table row for milestone 3 → built, the "AWS Lambda and DynamoDB" section (what, why, rejected: one Lambda per tool, token design, Deutschland-Ticket deviation), the end-to-end request section if it names the tools, the cost table and the "Where the code is" table. Verify: every relative link in the file resolves (`grep -o '](\.\./[^)]*)'` paths exist).
- [ ] 5.3 Update `docs/INTERVIEW.md`: add questions and answers for what this change built (why the LLM never computes money, how the confirmation token works, why one Lambda per tool, how idempotency works, what the sources do and don't settle, how the handlers already fit the Gateway), rewrite any *(planned)* answer that is now built, and update the "Last updated by" line to `tools` (milestone 3). Verify: no answer about tools is still marked *(planned)*.
- [ ] 5.4 Run `/devflow:verify` and confirm PASS. Record any known gaps under Risks / Trade-offs in design.md. After PASS, push and open the draft PR (`gh pr create --draft`, body links `openspec/changes/tools/`).

## 6. Live checks (user runs or approves; each step needs explicit go-ahead)

- [ ] 6.1 With fresh `railagent` credentials, run `scripts/deploy.sh`. Verify: `RailRightsAgent-Tools` is `CREATE_COMPLETE` in eu-north-1 with the four tags, the five outputs, two tables and three functions. Cost: about $0.
- [ ] 6.2 Run `uv run python -m rail_rights_agent.tools seed`, then `... delay "ICE 123" 2026-11-20`. Verify: the seed reports the number of trips written, and the probe prints the 120-minute record. Cost: about $0.
- [ ] 6.3 Run `uv run pytest -q -m live tests/live/test_tools_live.py`. Verify: 1 passed; record the cold-start duration from the function's log in design.md. Cost: about $0.
- [ ] 6.4 Your call: leave the stack running for `agent-local` (about $0 idle), or run `scripts/destroy.sh` and verify no table, function or `/aws/lambda/RailRightsAgent-Tools*` log group remains. Record the decision in design.md.

## Workflow follow-up

- Set roadmap entry 3 to done (with the archive folder), and note under "Learned / carried forward" the Deutschland-Ticket deviation, the token design and the shared `rail_rights_agent/aws.py` for `agent-local` and `agentcore`.
- `/opsx:archive tools` on the branch, then `/devflow:land-branch`.
