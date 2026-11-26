# Proposal

## Why

The agent must never let the LLM compute money: compensation under Art. 19 of Regulation (EU) 2021/782 and the DB conditions of carriage has to be deterministic, and a claim may only be submitted after the user has confirmed a concrete summary. Nothing can look up a delay, compute an amount or record a claim yet. This change builds those three tools as pure Python plus thin Lambda handlers, so that `agent-local` (roadmap #4) can call them in-process and `agentcore` (#5) can expose the same Lambdas through the Gateway as MCP tools.

## What Changes

- **Compensation calculation** (`calculate_compensation`), deterministic and table-driven from the two source documents:
  - Art. 19(1): 25 % of the ticket price for a delay of 60–119 minutes, 50 % from 120 minutes.
  - Art. 19(3): a return ticket without a per-leg price counts at half its price.
  - Art. 19(9) and 19(1): no compensation when the passenger was informed of the delay before buying, or when the ticket was already reimbursed under Art. 18.
  - Art. 19(10): no compensation for extraordinary circumstances, passenger fault or third-party behaviour; strikes by the railway's own staff and infrastructure failures stay compensable (last sentence of 19(10)).
  - DB conditions A.9.2.1: rounding to cents, amounts under €4 not paid out (the Art. 19(8) threshold).
  - DB conditions B.13.1 and C.3.10.1: flat rates for long-distance season tickets (€5 / €7.50 per case, 2nd / 1st class) and BahnCard 100 (€10 / €15), each capped at 25 % of the ticket price.
  - Every result carries structured legal references (document id and article or clause) that the agent can retrieve and cite, and a confirmation token that binds the computed amount to its inputs.
- **Train delay lookup** (`get_train_delay`) over a mock trips table: scheduled and actual times, delay in minutes, status (on time, delayed, cancelled) and the cause category used by the exclusion rules. A seed command loads about a dozen fixed trips covering every rule.
- **Claim submission** (`submit_claim`): requires the confirmation token from a matching calculation, writes the claim once (idempotent: a repeated submission returns the same claim id and says so), and stores it in a claims table that is the single source of truth (roadmap decision 3).
- A new `RailRightsAgent-Tools` stack: two on-demand DynamoDB tables, three Python 3.12 Lambda functions with least-privilege table access and short-lived log groups, and stack outputs for the table names and function ARNs. Deployed and destroyed by the existing one-command scripts.
- Shared AWS helpers (`boto3` session from settings, stack-output lookup) move from the knowledge-base package to a shared module, so the seed command and the knowledge-base ingestion use the same code. The knowledge-base behaviour does not change.
- **Deviation from the roadmap:** the roadmap lists "Deutschlandticket flat rates". The DB document in `docs/source/` only says (C.3.10.3) that Deutschland-Ticket passenger rights follow the Deutschland-Ticket tariff, which is not one of our source documents and may not be downloaded. The tool therefore reports Deutschland-Ticket claims as not computable from the sources and cites that clause, rather than hardcoding uncited numbers. The same applies to regional season tickets (Verbund tariffs). This can be revisited if the tariff document is added later.

## Capabilities

### New Capabilities
- `compensation-calculation`: the deterministic compensation rules (eligibility, percentage, rounding, minimum payout, flat rates), the structured legal references each result carries, and the confirmation token.
- `train-delay-lookup`: looking up a train's delay record by train number and travel date from the trips store, the seed data set and its storage.
- `claim-submission`: recording a confirmed compensation claim exactly once, the confirmation-token check, and the claims store.
- `tool-functions`: the contract every tool Lambda follows: arguments in, JSON result or structured error out, least-privilege permissions, outputs for later milestones.

### Modified Capabilities
None. No existing requirement changes; the knowledge-base helpers are moved, not changed.

## Impact

- **Code:**
  - new `src/rail_rights_agent/tools/` (domain logic, handlers, seed data, CLI)
  - new `src/rail_rights_agent/aws.py` (shared session and stack-output helpers; `knowledge_base` imports from it)
  - new `infra/stacks/tools.py`, wired into `infra/app.py`
  - tests under `tests/unit/tools/`, `tests/infra/` and `tests/live/`
  - README development section (seed and probe commands), `docs/ARCHITECTURE.md`, `docs/INTERVIEW.md`
- **Dependencies (need your approval):**
  - `hypothesis` in the `dev` group, for the property-based tests the roadmap asks for (monotonic in delay, bounded by 50 % of the price, payout is 0 or at least €4, token stable under identical inputs). Alternative without a new dependency: hand-written parametrised sweeps; weaker, but possible if you prefer.
  - `boto3-stubs` gains the `dynamodb` and `lambda` extras (same dev dependency, two more service stubs) so strict mypy covers the new calls.
  - No new runtime dependency: the Lambdas use only the standard library and the `boto3` already in the Lambda runtime.
- **Live and billed resources** (final task group only, each step with your go-ahead): DynamoDB on-demand (two tables, kilobytes of data, a few hundred requests), three Lambda functions (a few hundred invocations of 256 MB, well inside the free tier), CloudWatch Logs (kilobytes, 7-day retention). **Estimated total for this milestone: under $0.05;** idle cost about $0, so the stack can stay deployed for `agent-local`. The roadmap estimated about $0.
- **Not touched:** the knowledge-base stack, the budget, the model configuration. No AgentCore resources yet (milestone 5); the handlers are written against the Gateway's documented Lambda event format so they need no change then.
