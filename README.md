# Rail Rights Agent

Bilingual (DE/EN) AI agent on AWS Bedrock AgentCore that explains rail passenger rights under
EU Regulation 2021/782 and Deutsche Bahn conditions of carriage, checks train delays, computes
compensation and submits a claim after explicit confirmation.

> Work in progress. The full README with architecture, evaluation and cost results comes with the
> `portfolio-docs` change.

## Development

Requirements: [uv](https://docs.astral.sh/uv/), Node.js 20+ (for the CDK and OpenSpec CLIs, run
pinned through `npx`), and for deploys the AWS CLI with the `railagent` profile.

```bash
uv sync                # Python 3.12 venv with dev + infra dependencies from uv.lock
scripts/check.sh       # every offline gate: lint, format, mypy, tests, openspec validate, secrets
uv run pytest -q       # offline tests only; tests marked `live` are excluded by default
```

The first `mypy` run analyses aws-cdk-lib and takes several minutes and ~3 GB RAM; later runs use
the cache and take seconds.

### Configuration

All settings have defaults and can be overridden with `RAILAGENT_*` environment variables; see
[`.env.example`](.env.example). Model ids live only in
[`src/rail_rights_agent/settings.py`](src/rail_rights_agent/settings.py). The region is locked to
`eu-north-1`.

### Deploy and destroy

Both commands create or delete real AWS resources in eu-north-1 with the configured profile.

```bash
scripts/deploy.sh --dry-run   # print the target and synthesise only; no AWS calls
scripts/deploy.sh             # deploy every stack
scripts/destroy.sh            # destroy every stack
```

Set `RAILAGENT_BUDGET_EMAIL` (never commit it) to also deploy a monthly cost budget with email
alerts at 50 % and 80 % of actual and 100 % of forecast spend (`RAILAGENT_BUDGET_LIMIT_USD`,
default 20).

### Knowledge base

The knowledge base (Bedrock Knowledge Base on S3 Vectors, Titan Text Embeddings V2) holds
Regulation (EU) 2021/782 in English and German and the DB conditions of carriage. The source PDFs
are not committed: put `eu-2021-782-en.pdf`, `eu-2021-782-de.pdf` and
`db-befoerderungsbedingungen-de.pdf` in `docs/source/`. After `scripts/deploy.sh`, ingest them,
then query. Both commands are live and use the configured profile:

```bash
uv run python -m rail_rights_agent.knowledge_base --help
uv run python -m rail_rights_agent.knowledge_base ingest       # upload + ingestion job, ~minutes
uv run python -m rail_rights_agent.knowledge_base retrieve "Entschädigung bei 60 Minuten Verspätung?" --language de
uv run pytest -q -m live tests/live                            # live smoke test (billed, cents)
```

Re-run `ingest` after replacing a PDF. `scripts/destroy.sh` deletes the documents and vectors too.

### Tools

The agent's three tools (`get_train_delay`, `calculate_compensation`, `submit_claim`) are plain
Python in `src/rail_rights_agent/tools/`, deployed by the `RailRightsAgent-Tools` stack as one
Lambda function each over two on-demand DynamoDB tables. After `scripts/deploy.sh`, seed the mock
trips, then probe. `seed` and `delay` are live; `compensate` runs offline:

```bash
uv run python -m rail_rights_agent.tools --help
uv run python -m rail_rights_agent.tools seed                          # write the mock trips (live)
uv run python -m rail_rights_agent.tools delay "ICE 123" 2026-11-20    # look one up (live)
uv run python -m rail_rights_agent.tools compensate --price 29.90 --delay 75   # offline
uv run pytest -q -m live tests/live/test_tools_live.py                # live round trip (billed, ~$0)
```

Compensation is computed from Art. 19 of Regulation (EU) 2021/782 and the DB conditions; every
result lists the clauses it rests on. Deutschland-Ticket and regional season tickets are reported
as not computable from the source documents.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): components, AWS services and why each was chosen.
- [docs/INTERVIEW.md](docs/INTERVIEW.md): interview questions and answers about the project.
- [docs/ROADMAP.md](docs/ROADMAP.md): milestone plan.

## How to contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for the spec-driven change loop.
