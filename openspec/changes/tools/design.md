# Design

## Context

See proposal.md for motivation. What this change builds on:
- `infra/app.py::build_app` creates the stacks; `apply_project_tags` tags them; `tests/infra/test_app.py` walks every synthesised resource for tags, so a new stack is covered automatically.
- `rail_rights_agent.knowledge_base` has `aws.clients(settings)` (a `boto3.Session` from the `railagent` profile) and `ingest.resolve_stack_outputs(cfn, stack_name)`. The knowledge-base design noted both will be shared later.
- `catalogue.py` defines the document ids `eu-2021-782` and `db-befoerderungsbedingungen`; the compensation references reuse them so the agent can retrieve and cite the passage.
- Offline tests use botocore `Stubber` with dummy credentials (`tests/unit/knowledge_base/conftest.py`); live tests are `@pytest.mark.live`.

**Rules taken from the source documents** (read 2026-11-26 from `docs/source/`):
- `eu-2021-782-en.pdf`, Art. 19 (OJ L 172/19–20): (1) 25 % for 60–119 min, 50 % from 120 min, no compensation if reimbursed under Art. 18; (3) return ticket without a leg price → half the price; (8) threshold of at most €4 per ticket; (9) informed before purchase, or re-routing delay under 60 min → nothing; (10)(a)–(c) exclusions, and the last sentence keeps own-staff strikes and infrastructure/station managers compensable.
- `db-befoerderungsbedingungen-de.pdf`: A.9.2.1 (p. 30) 25 %/50 %, "kaufmännisch" rounding to 2 decimals, once per ticket and per direction for return tickets, under €4 not paid, Art. 19(10) reserved; B.13.1 (p. 44) ICE/IC-EC Zeitkarte €5 / €7.50 per case from 60 min, max 25 % of the price in total; C.3.10.1 (p. 55) BahnCard 100 €10 / €15, max 25 % of the BahnCard price; C.3.10.3 Deutschland-Ticket rights follow the Deutschland-Ticket tariff (not in our sources).

**Verified against AWS docs (aws-docs MCP, 2026-11-26):** an AgentCore Gateway Lambda target receives the tool arguments as the `event` (a map of the `inputSchema` properties) and the metadata (`bedrockAgentCoreToolName` etc.) in `context.client_context.custom`; the function must return valid JSON. Tool names get a `<target>___` prefix that a multi-tool function would have to strip. (`gateway-add-target-lambda.html`)

## Goals / Non-Goals

**Goals:**
- Pure, typed, dependency-free domain functions the agent (milestone 4) imports directly and the Lambdas wrap in a few lines.
- Handlers already shaped for the Gateway (milestone 5): arguments in, JSON out, errors as data.
- Every number traceable to a clause the knowledge base can retrieve.
- Offline tests for every spec scenario; one live round trip.

**Non-Goals:**
- Real DB delay data or any external API: trips are seeded mock data.
- Cumulative rules: adding ≥20-minute delays towards the 60-minute threshold (B.13.1), the 25 % cap across many cases (B.13.1, C.3.10.1), and Art. 19(2) recurrent-delay arrangements. The result notes the cap; prior payouts are not tracked.
- Deutschland-Ticket and regional (Verbund) season-ticket amounts (proposal, deviation).
- Refunds and re-routing (Art. 18), assistance (Art. 20), expenses (DB 9.1.5/9.1.6): the agent explains these from retrieved passages; nothing to compute.
- Real claim processing or payment, PII masking (milestone 6), MCP exposure (milestone 5).

## Decisions

### D1. Domain model and rules table (`rail_rights_agent/tools/compensation.py`)
- **Choice:** Frozen dataclasses and `StrEnum`s, money as `Decimal`:
  - `TicketKind`: `SINGLE`, `RETURN`, `SEASON_LONG_DISTANCE`, `BAHNCARD_100`, `DEUTSCHLAND_TICKET`, `SEASON_REGIONAL`.
  - `DelayCause`: `OPERATIONAL`, `OWN_STAFF_STRIKE`, `INFRASTRUCTURE`, `EXTREME_WEATHER`, `PASSENGER_FAULT`, `THIRD_PARTY`, `UNKNOWN`. Excluded set: `{EXTREME_WEATHER, PASSENGER_FAULT, THIRD_PARTY}` → Art. 19(10)(a)/(b)/(c). Everything else is compensable (19(10) last sentence; unknown → burden of proof on the railway).
  - `CompensationRequest(ticket_price_eur, delay_minutes, ticket_kind, travel_class=2, cause=UNKNOWN, informed_before_purchase=False, reimbursed_under_art_18=False)`.
  - `Compensation(eligible, computable, percentage, base_price_eur, compensation_eur, payout_eur, reason: ReasonCode, references: tuple[LegalReference, ...], notes: tuple[str, ...], confirmation_token: str | None)`.
  - `LegalReference(document, label)` with `document` one of the catalogue ids, e.g. `("eu-2021-782", "Art. 19(1)(a)")`, `("db-befoerderungsbedingungen", "A.9.2.1")`.
  - `ReasonCode`: `ELIGIBLE`, `BELOW_60_MINUTES`, `INFORMED_BEFORE_PURCHASE`, `REIMBURSED_UNDER_ART_18`, `EXCLUDED_EXTRAORDINARY`, `EXCLUDED_PASSENGER_FAULT`, `EXCLUDED_THIRD_PARTY`, `BELOW_MINIMUM_PAYOUT`, `NOT_COMPUTABLE_FROM_SOURCES`.
  - `calculate_compensation(request) -> Compensation` evaluates in this order: validation → not-computable kinds → informed-before-purchase → reimbursed → excluded cause → delay band → amount (percentage of base, or flat rate capped at 25 %) → round `ROUND_HALF_UP` to cents → minimum payout → token.
  - Flat rates and thresholds live in one module-level table with the clause next to each number.
- **Why:** The rules are few and tabular; a table with references beside the numbers is auditable against the PDFs. `Decimal` avoids float rounding on money. `StrEnum` serialises directly to the JSON the handlers return and the agent's tool schema can enumerate.
- **Rejected:**
  - A rules engine or declarative DSL: over-engineering for nine reason codes.
  - Floats and `round()`: banker's rounding differs from "kaufmännisch" at .5 (7.475 → 7.48 is required).
  - Treating `UNKNOWN` cause as excluded: contradicts Art. 19(10), which makes the railway prove the exemption.

### D2. Confirmation token: deterministic digest, not a secret
- **Choice:** `confirmation_token = sha256(canonical JSON of the request fields that affect the amount + payout)[:16]` upper-case hex, issued only when `payout_eur > 0`. `submit_claim` recomputes it from the submitted fields and requires equality.
- **Why:** It binds a submission to a computation the tool itself performed: the LLM cannot submit an amount it made up, or a claim for a trip it never evaluated. It is stateless, so the compensation Lambda needs no table. The human confirmation step ("show the summary, wait for yes") is the agent's responsibility in milestone 4; this token is the tool-level half of that two-phase flow, and the design says so plainly.
- **Rejected:**
  - HMAC with a secret: needs a secret in two Lambdas and Secrets Manager (idle cost) and protects against an adversary we don't have; the model is not trying to forge digests.
  - A server-side pending-claims table with TTL: stateful, a third table, and the same guarantee.
  - Random token stored at calculation time: same as above.

### D3. Delay lookup (`rail_rights_agent/tools/delays.py`) and seed data (`seed_data.py`)
- **Choice:**
  - `TripRecord` frozen dataclass: `train_number` (normalised: upper-case, spaces removed), `travel_date` (`date`), `origin`, `destination`, `scheduled_departure`, `scheduled_arrival` (`datetime` with offset), `actual_arrival: datetime | None`, `delay_minutes: int`, `status: TripStatus`, `cause: DelayCause`.
  - `normalise_train_number("ice 123") == "ICE123"`; `parse_travel_date` rejects invalid dates before any AWS call.
  - `TripStore(dynamodb_client, table_name).get(train_number, travel_date) -> TripRecord` raising `TripNotFound`; `.put_many(records)` for seeding.
  - DynamoDB item shape: `pk = train_number`, `sk = travel_date` (ISO), other fields as `S`/`N`; `actual_arrival` omitted when cancelled. Low-level client with explicit attribute maps (typed by boto3-stubs), no `resource` API.
  - `SEED_TRIPS`: about 12 fixed trips on fixed dates in November 2026 (e.g. `ICE 123` Berlin→München 2026-11-20, 120 min, operational), covering the spec's list. Seeding uses `PutItem` per record (12 items), so re-running overwrites the same keys and cannot duplicate.
- **Why:** Composite key makes the lookup a single `GetItem`; normalising at write and read time makes `ice 123` work without a scan. Fixed dates make the evaluation set (milestone 7) reproducible.
- **Rejected:**
  - Relative dates ("yesterday"): non-reproducible tests and evals.
  - `BatchWriteItem`: 12 items don't need it, and `PutItem` keeps the stub tests one-call-per-record.
  - A real timetable API: the roadmap says mock, and no DB API is free of keys and terms.

### D4. Claim submission (`rail_rights_agent/tools/claims.py`)
- **Choice:**
  - `ClaimRequest`: the `CompensationRequest` fields plus `train_number`, `travel_date`, `passenger_name`, `email`, `iban: str | None`, `confirmation_token`.
  - `ClaimStore(dynamodb_client, table_name)`; `submit_claim(store, request, now=datetime.now) -> ClaimReceipt(claim_id, payout_eur, already_submitted, submitted_at)`.
  - Order: validate fields → `calculate_compensation` → payout 0 → `ClaimRejected(reason)`; token mismatch → `ClaimRejected("CONFIRMATION_MISMATCH")`; `claim_id = "CLM-" + token`; `PutItem` with `ConditionExpression="attribute_not_exists(claim_id)"`; on `ConditionalCheckFailedException` → `GetItem` and return the existing receipt with `already_submitted=True`.
  - Item: every field in the spec, money as `N` strings, `status = "submitted"`, `submitted_at` ISO UTC.
- **Why:** The condition expression makes the write idempotent without a read-before-write race. Deriving the id from the token means "same confirmed claim" and "same id" are the same thing. `now` is injected for tests.
- **Rejected:**
  - UUID claim ids plus a token GSI: a second index and a query for the same guarantee.
  - Storing only a hash of the IBAN: the roadmap's guardrail decision (2) says claim fields reach the tool unmasked; masking happens on outputs and logs in milestone 6. The data is mock in any case.

### D5. Handlers (`rail_rights_agent/tools/handlers.py`) and the error contract
- **Choice:** Three module-level handlers, `get_train_delay(event, context)`, `calculate_compensation(event, context)`, `submit_claim(event, context)`, each: parse `event` into the request dataclass (`from_event` classmethods that coerce JSON strings and numbers), call the domain function, return `asdict`-style JSON with `Decimal` as strings (`"25.00"`) and enums as their values. Domain errors (`ValidationError`, `TripNotFound`, `ClaimRejected`) and `botocore.ClientError` become `{"error": {"code": ..., "message": ...}}`; nothing is raised. `context` is accepted and ignored. Table names come from `TRIPS_TABLE` / `CLAIMS_TABLE` environment variables; the DynamoDB client is created lazily and cached per container.
- **Why:**
  - One function per tool: least-privilege IAM per function, no tool-name prefix parsing, and in milestone 5 each becomes a Gateway target with a one-tool schema. The event is exactly the Gateway's event.
  - Errors as data: a raised exception reaches the Gateway as an opaque failure; a structured `error` lets the model tell the user "no record for ICE 999 on that date". The agent (milestone 4) uses the same objects in-process.
  - Decimal as strings: JSON floats would reintroduce the rounding we avoided.
- **Rejected:**
  - One Lambda dispatching on `bedrockAgentCoreToolName`: broader IAM, prefix handling, and a bigger blast radius.
  - Pydantic for parsing: a new runtime dependency to validate three flat objects.
  - AWS Lambda Powertools: another dependency and a layer; nothing here needs it.

### D6. Stack (`infra/stacks/tools.py::ToolsStack`, `RailRightsAgent-Tools`)
- **Choice:**
  - Two `dynamodb.TableV2` tables (`Trips`: `pk` S + `sk` S; `Claims`: `claim_id` S), `billing=Billing.on_demand()`, `removal_policy=DESTROY`, default AWS-owned encryption, point-in-time recovery off, generated names.
  - Three `lambda_.Function`s: `Runtime.PYTHON_3_12`, `architecture=ARM_64`, `memory_size=256`, `timeout=10 s`, `code=Code.from_asset("src", exclude=["**/__pycache__", "**/*.pyc", "rail_rights_agent/knowledge_base/**"])`, handler `rail_rights_agent.tools.handlers.<name>`, `environment` with the table names where needed, and `log_group=logs.LogGroup(retention=ONE_WEEK, removal_policy=DESTROY)`.
  - Grants: `trips.grant_read_data(delay_fn)`; `claims.grant(submit_fn, "dynamodb:GetItem", "dynamodb:PutItem")`; nothing for the compensation function.
  - Outputs: `TripsTableName`, `ClaimsTableName`, `GetTrainDelayFunctionArn`, `CalculateCompensationFunctionArn`, `SubmitClaimFunctionArn`. Names shared with the Python side in `rail_rights_agent/tools/deployment.py`, mirroring `knowledge_base/deployment.py`.
- **Why:**
  - The domain code is pure Python and the Lambda runtime ships boto3, so a plain directory asset works with no Docker bundling (important on this 5.8 GB WSL host) and no `aws-lambda-python-alpha` dependency.
  - ARM is cheaper per ms and Python 3.12 is available on it; 256 MB is plenty for `Decimal` arithmetic and one DynamoDB call.
  - A stack-owned log group fixes the leftover-log-group problem noted in knowledge-base D5 for these functions.
  - `TableV2` is the current L2 with on-demand as a first-class option.
- **Rejected:**
  - `aws_lambda_python_alpha.PythonFunction`: alpha package, Docker bundling, new dependency.
  - A single table with both entity types: two tables keep IAM scoping readable and match roadmap decision 3 ("the claims table").
  - Provisioned capacity: idle cost outside the free tier later; on-demand at this volume is cents.
  - The asset including `knowledge_base/`: harmless but 2× the zip and a confusing import surface in the function.

### D7. Shared AWS helpers (`rail_rights_agent/aws.py`)
- **Choice:** Move `session(settings) -> boto3.Session` (the profile/region logic of `knowledge_base/aws.clients`) and `resolve_stack_outputs(cfn, stack_name)` into `rail_rights_agent/aws.py`. `knowledge_base.aws.clients` and `knowledge_base.ingest.resolve_stack_outputs` keep working by importing from there, so the existing knowledge-base tests are untouched. The tools CLI (`python -m rail_rights_agent.tools seed | delay | compensate`) builds its DynamoDB client from the same session and reads table names from the `RailRightsAgent-Tools` outputs.
- **Why:** Two commands need the same two helpers; the knowledge-base design already flagged the move. The handlers do not use this module: in Lambda there is no profile, and they build a plain `boto3.client("dynamodb")`.
- **Rejected:** importing from `knowledge_base.ingest` in the tools package: a tools→knowledge-base import for a CloudFormation helper is the wrong direction.

### D8. Dependencies
- **Choice (need approval):** `hypothesis` in `dev`; `boto3-stubs` extras extended with `dynamodb,lambda`. No runtime dependency changes.
- **Why:** The roadmap asks for property-based tests; Hypothesis is the standard tool and finds rounding edge cases that a table misses. The stubs keep strict mypy over the new boto3 calls.
- **Rejected:** hand-rolled random sweeps (no shrinking, weaker), `moto` (Stubber is enough, as before).

### D9. Tests
- **Unit (`tests/unit/tools/`):** `test_compensation.py` has one parametrised case per spec scenario plus Hypothesis properties (bounded by 50 %, monotonic in delay, payout 0 or ≥ 4, token stable, token changes with price). `test_delays.py` and `test_claims.py` use `Stubber` on a DynamoDB client (fixtures copied from the knowledge-base conftest into a shared `tests/unit/conftest.py`): item mapping, normalisation, not-found, invalid date before any call, seed idempotency (same keys), conditional put, `ConditionalCheckFailedException` → existing receipt, rejection before any call. `test_handlers.py` drives the three handlers with Gateway-shaped events and asserts the JSON and `error` shapes. `test_seed_data.py` checks the coverage list.
- **Infra (`tests/infra/test_tools_stack.py`):** billing mode, keys, deletion policy; runtime, timeout, ARM, env vars, log groups; per-function policies (resource names, action sets, no `*`); the five outputs. `test_app.py`'s tag walk covers the new stack unchanged.
- **Live (`tests/live/test_tools_live.py`):** one test for the round trip in the `tool-functions` spec, invoking the functions by ARN from the stack outputs.

## Risks / Trade-offs

- **Rule interpretation.** The percentages, threshold and flat rates are read directly from the PDFs; the exclusion categories are a simplification of 19(10). → Each number sits beside its clause in code and in the spec; the agent cites the retrieved passage, and the eval set (milestone 7) exercises the edge cases. Anything the sources don't settle returns `NOT_COMPUTABLE_FROM_SOURCES` instead of a guess.
- **Deutschland-Ticket is a common real question** and the tool declines it. → The result cites C.3.10.3 and the agent explains where the rule lives. Adding the tariff PDF to the catalogue later is a small follow-up change.
- **The token is not a secret.** A caller who knows the scheme can mint one. → Accepted: the callers are our own agent and, later, the Gateway behind Cognito; the goal is to prevent fabricated amounts, not to authenticate users.
- **Cumulative caps are not enforced** (25 % over a validity period). → Stated in `notes`; the claims table holds the history if a later change wants to enforce it.
- **PII (name, email, IBAN) in DynamoDB and potentially in logs.** → Handlers log nothing but error codes; masking of outputs and Memory is milestone 6 (roadmap decision 2); the data is mock; tables are encrypted and destroyed with the stack.
- **Lambda cold start with `Decimal` and dataclasses** is small (~100 ms); no third-party imports. → Measured in the live check and recorded here.
- **Asset from `src/` picks up stray files.** → Explicit excludes; the infra test asserts the handler paths; the live invoke proves the import works.
- **Seed data drifts from the rule set** as rules change. → `test_seed_data.py` asserts coverage of every delay band, status and cause.

## Migration Plan

- Offline groups change nothing in AWS. The knowledge-base helper move is import-compatible.
- **Live group, each step with your go-ahead:**
  1. `scripts/deploy.sh` (adds `RailRightsAgent-Tools`; other stacks unchanged, the knowledge-base stack is currently destroyed and stays so).
  2. `uv run python -m rail_rights_agent.tools seed`, then `... delay "ICE 123" 2026-11-20` as a probe.
  3. `uv run pytest -q -m live tests/live/test_tools_live.py`.
  4. Your call: leave the stack running (about $0 idle, saves re-seeding for `agent-local`) or `scripts/destroy.sh` and confirm no tables, functions or log groups remain.
- **Rollback:** `scripts/destroy.sh` removes the stack and its data; or revert the branch. Nothing depends on the tools yet.
