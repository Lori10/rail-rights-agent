# Interview questions

Questions an interviewer is likely to ask about this project, with answers. Each answer gives
the decision, the reason and the trade-off, short enough to say out loud in about a minute.
Details and evidence are in the linked `design.md` files and [ARCHITECTURE.md](ARCHITECTURE.md).

**Kept current by every change:** a change that adds or alters something updates this file in its
own PR (rule in [`openspec/config.yaml`](../openspec/config.yaml)). It adds questions for what it
built and rewrites any *planned* answer that is now built.

Last updated by: `tools` (milestone 3). Built so far: foundation, knowledge base, tools.
Questions marked *(planned)* describe the agreed design; they are not built yet.

**Contents:** [1. The pitch](#1-the-pitch) ·
[2. Architecture and AWS choices](#2-architecture-and-aws-choices) ·
[3. Retrieval (RAG)](#3-retrieval-rag) ·
[4. Infrastructure as code](#4-infrastructure-as-code) ·
[5. Security](#5-security) · [6. Cost](#6-cost) ·
[7. Testing and quality](#7-testing-and-quality) ·
[8. How the work is run](#8-how-the-work-is-run) ·
[9. Problems hit and lessons](#9-problems-hit-and-lessons) ·
[10. Tools and the agent](#10-tools-and-the-agent)

---

## 1. The pitch

### What is this project, in 30 seconds?
A bilingual (German/English) AI agent for rail passengers. You describe a delayed or cancelled
train; it explains your rights under EU Regulation 2021/782 and the Deutsche Bahn conditions of
carriage, citing the actual legal passages. For a concrete trip it looks up the delay, computes
the compensation in code and, only after you confirm, submits the claim. It runs on AWS: Bedrock
models, Bedrock Knowledge Bases on S3 Vectors, and AgentCore for hosting.

### Why this problem?
It has the features that make agents hard in practice: answers must be grounded in legal text,
there is money involved (so arithmetic can't be left to the model), there is a real-world action
(submitting a claim) that needs a human confirmation, and users write in two languages. A
chatbot demo avoids all of these; this project has to handle each one.

### What is built today, and what is still planned?
Built: the foundation (project setup, quality gates, tagged CDK infrastructure, region lock,
cost budget), the knowledge base (legal PDFs ingested into S3 Vectors, a tested retrieval client
returning passages with document, language and page) and the three tools (delay lookup,
deterministic compensation, idempotent claim submission) as Lambda functions over DynamoDB.
Planned, in order: the local agent, AgentCore hosting, Guardrails, evaluation, UI and
observability.
The order is in [ROADMAP.md](ROADMAP.md).

### What is the most important design rule?
**The model explains, code decides.** Compensation is calculated by deterministic Python
(Art. 19: 25 % of the fare from 60 minutes of delay, 50 % from 120, plus DB rules such as the
€4 minimum payout); the model never does that arithmetic. LLMs are good at explaining and bad at
exact, auditable rules. The other two rules follow the same idea: every rights answer cites a
retrieved passage, and no claim is submitted without explicit confirmation.

---

## 2. Architecture and AWS choices

### Walk me through one request end to end.
The user asks in the chat; the Strands agent on AgentCore Runtime sends it to Claude Haiku 4.5.
The model asks for legal context, so the agent calls Knowledge Bases `Retrieve` with a language
filter and gets the top passages. It asks for the trip, so the agent calls `get_train_delay`
through AgentCore Gateway. `calculate_compensation` computes the amount in code. The model
explains the result with citations and shows a claim summary; only after "yes" does it call
`submit_claim`. Retrieval and the three tools work today (through their CLIs and Lambda); the
agent loop and hosting are planned. The full flow is in
[ARCHITECTURE.md](ARCHITECTURE.md#one-request-end-to-end).

### Why AgentCore and not Bedrock Agents?
Bedrock Agents (Classic) is closed to new customers, so it isn't an option for new work.
AgentCore lets me write the agent in an open framework (Strands) and host it on a runtime billed
only while a request is active. Gateway turns plain Lambdas into MCP tools, so the tools aren't
tied to one agent framework.

### Why S3 Vectors instead of OpenSearch Serverless?
Cost. OpenSearch Serverless bills for capacity even when nobody is querying; for a project used
in bursts that is the biggest line on the bill. S3 Vectors is pay per use with storage at cents
per month, and Knowledge Bases supports it as a store. The trade-off: semantic search only (no
keyword or hybrid search) and tight metadata limits. A test fails the build if any OpenSearch
Serverless resource appears.
[knowledge-base D3](../openspec/changes/archive/2026-11-01-knowledge-base/design.md)

### Why use Bedrock Knowledge Bases instead of writing your own RAG pipeline?
It handles PDF parsing, chunking, embedding and writing to the vector store, which is plumbing,
not the interesting part of this project. I call only `Retrieve`, not `RetrieveAndGenerate`,
so the agent keeps control of the answer and of how citations are formatted.

### Which models, and why two?
Claude Haiku 4.5 is primary: fast, cheap, good at tool use and German. Amazon Nova 2 Lite is the
comparison model, so the evaluation milestone can report quality and cost per model instead of
guessing. Both are EU cross-region inference profiles. Model ids live only in `settings.py`, and
a test fails if one is hard-coded anywhere else, so switching models is a config change.

### Why one region (eu-north-1)?
It keeps data in the EU and keeps the setup simple. It is enforced twice: the settings refuse any
other region, and an account-level SCP denies every other region. The cost of this choice is
that some services are missing or limited there (see [§9](#9-problems-hit-and-lessons)).

---

## 3. Retrieval (RAG)

### How are the documents ingested?
Three PDFs (2021/782 in English and German, DB conditions in German). An ingest command uploads
each PDF plus a small `.metadata.json` sidecar tagging it with `document` and `language`, then
starts a Knowledge Base ingestion job and polls it. Bedrock parses, chunks (300 tokens, 20 %
overlap), embeds with Titan V2 and writes vectors to S3 Vectors. It takes about 40 seconds.

### Why upload the PDFs with a command and not with CDK?
The PDFs are gitignored (`docs/source/`), so a CDK asset would break synthesis in CI and in the
offline tests. Making it conditional would be worse: a deploy without the folder would silently
empty the bucket. A command that uploads exactly the catalogued files is explicit and testable,
and a stray file can never enter the knowledge base.
[knowledge-base D5, D6](../openspec/changes/archive/2026-11-01-knowledge-base/design.md)

### Why Titan Text Embeddings V2 and not Cohere Embed v4?
Cohere is better at multilingual and cross-language matching, and was my first choice. But in
eu-north-1 it is reachable only through a cross-region inference profile, and Knowledge Bases
don't document support for that as an embedding model. Titan V2 is the only KB embedding model
available in-region, is multilingual, and costs $0.00002 per 1K tokens. Live tests rank the right
article first in both languages (scores ~0.75–0.79).
[knowledge-base D2](../openspec/changes/archive/2026-11-01-knowledge-base/design.md)

### How do you handle two languages?
Each chunk carries a `language` attribute from its sidecar, and retrieval can filter on it
server-side. Titan's cross-language matching is weaker, so the agent will search in the user's
language: a German question gets German passages. Because the filter runs in the vector search,
the top-k results are all in the requested language, not a mix trimmed afterwards.

### Why 300-token fixed-size chunks?
Articles in 2021/782 and the DB clauses are short; 300 tokens fits a paragraph with room to
spare, and 20 % overlap keeps a sentence that crosses a boundary retrievable. I rejected
hierarchical chunking (its parent context can exceed S3 Vectors metadata limits) and semantic
chunking (extra embedding cost, less predictable sizes). The evaluation milestone can revisit
this if articles get split badly.
[knowledge-base D4](../openspec/changes/archive/2026-11-01-knowledge-base/design.md)

### How do you make citations possible?
Retrieval returns a typed `Passage`: text, document, language, S3 source, score and page number.
The agent cites from those fields rather than from what the model remembers. The page number
comes from Bedrock's PDF parser; it wasn't clearly documented for S3 Vectors, so it is optional in
the type, and the live test confirmed it is present.

### What did you have to know about S3 Vectors limits?
Filterable metadata is limited to 2 KB per vector, and the non-filterable keys can't be changed
after the index is created. Knowledge Bases store each chunk's text in the metadata, and a
300-token chunk alone exceeds 2 KB, so those Bedrock keys must be declared non-filterable when
the index is created. Our own `document` and `language` stay filterable. Getting this wrong
means replacing the index.

---

## 4. Infrastructure as code

### How is the infrastructure managed?
All of it is AWS CDK in Python, in [`infra/`](../infra/), one stack per concern (baseline,
budget, knowledge base). `scripts/deploy.sh` and `scripts/destroy.sh` create or remove everything
in one command, with the CDK CLI pinned through `npx`. Destroy really removes everything,
including documents and vectors, so nothing keeps costing money by accident.

### Did you use L1 or L2 constructs?
L2 where they exist (S3 bucket, IAM role) and L1 (`Cfn*`) for S3 Vectors and Bedrock Knowledge
Bases, which have no L2 yet. For new services that is normal; the stack tests check the
synthesised properties, so the extra verbosity of L1s doesn't hide mistakes.

### How do you stop CloudFormation from creating things in the wrong order?
The knowledge base checks its role's permissions when it is created, but CloudFormation could
create it before the policy is attached. I put the permissions in a separate `iam.Policy` and
added an explicit dependency from the knowledge base to it. Deletion order (data source → KB →
index → vector bucket) follows from the references.

### How are resources tagged?
One function applies four project tags to the whole app, and an infra test walks every
synthesised resource and fails if any is missing a tag. That makes cost reports and cleanup
reliable and turns "everything tagged" from a convention into something the build checks.

---

## 5. Security

### How are permissions scoped for the knowledge base?
One service role, trusted only by `bedrock.amazonaws.com` and only for this account's knowledge
bases (`aws:SourceAccount` and `aws:SourceArn` conditions, which stop the confused-deputy problem). It can invoke
only the embedding model, read only the `documents/` prefix and write only this vector index.
[knowledge-base D7](../openspec/changes/archive/2026-11-01-knowledge-base/design.md)

### How do you keep secrets and account details out of a public repo?
The account id is never in source code; CDK reads it from the credentials at deploy time.
Personal settings such as the budget email come from environment variables that are never
committed. Gitleaks scans every branch in `check.sh` and in CI, and GitHub push protection is on.
Credentials are short-lived (`aws login`, 12 h), not stored access keys.

### How is the S3 bucket protected?
Public access blocked, server-side encryption, TLS-only access enforced by bucket policy. It
holds only public legal texts, but the defaults cost nothing, so they are always on.

### What about prompt injection and personal data? *(planned)*
Bedrock Guardrails in milestone 6: prompt-attack filter, denied topics (e.g. legal
representation, non-rail requests), and PII masking for names, IBANs and DB booking numbers. The
subtle part is that masking input would remove the data a claim needs, so the plan is to mask
outputs, logs and Memory while claim fields reach `submit_claim` unmasked. A red-team set of
~80–100 prompts will measure block rate and false positives.

---

## 6. Cost

### What does it cost to run?
Design target is about $0 when idle: nothing is always on. Today the only standing cost is
S3 and vector storage at cents per month, plus fractions of a cent per ingestion or query. The
knowledge-base stack is destroyed between milestones and redeployed in about 2 minutes. The tools
stack (two on-demand tables, three Lambdas) costs about $0 idle and fractions of a cent per call.
The planned agent is estimated at $0.01–0.03 per conversation.

### How do you avoid a surprise bill?
Pay-per-use services only, one-command destroy, a test that bans OpenSearch Serverless, and a
$20/month AWS Budget emailing at 50 % and 80 % of actual and 100 % of forecast spend. The account
runs on free-plan credit, and using it up would close the account, so the alarm matters.

---

## 7. Testing and quality

### How do you test code that calls AWS without calling AWS?
Clients are passed in (dependency injection) and replaced in tests with botocore's `Stubber`,
which checks the exact request and returns a canned response. Even `sleep` is injected, so the
ingestion polling and timeout tests run instantly. I chose `Stubber` over `moto`: it needs no new
dependency and checks the exact request parameters.

### What test layers are there?
Three. **Unit** tests (offline, AWS stubbed), including property-based tests with Hypothesis
over the compensation rules. **Infra** tests that synthesise the CDK app and assert on the
CloudFormation (bucket hardening, index settings, IAM statements, Lambda runtimes and log groups,
tags, no OpenSearch). **Live** tests marked `live` that hit real AWS, excluded by default because they
are billed; they assert on keywords (e.g. `25`/`50`, `Erstattung`), never exact model output.

### What runs on every PR?
`scripts/check.sh`, the same script locally and in CI: ruff lint and format, strict mypy, pytest,
`openspec validate`, gitleaks, and a scan that flags removed assertions or added skips in test
files. `main` is protected: a PR can merge only with a green `checks` job, and there is no
bypass.

### Why strict mypy on a small project?
Most bugs here sit at boundaries: AWS responses mapped into our types. `boto3-stubs` plus strict
mypy catches a misspelled response key at check time instead of at runtime. The one place the
stubs are wrong (a metadata filter value) has a single commented `cast`.

### How do you stop tests being weakened to get green?
Tests come first from the spec scenarios, and an existing test may change only when its spec
changed. `scripts/weakened_tests.py` flags removed asserts and new skips in the diff for review,
and the commit history shows the red "failing tests" commit before each implementation.

---

## 8. How the work is run

### How do you go from idea to merged code?
Spec-driven with OpenSpec. Each milestone starts as a change folder with a proposal, delta specs
(requirements with scenarios), a design that records alternatives and why they were rejected,
and a task list. I approve that before any code. Then: failing tests, implementation, verify,
live checks, archive (the specs merge into `openspec/specs/`), and a PR with a merge commit.
[CONTRIBUTING.md](../CONTRIBUTING.md)

### What was the role of AI coding tools?
I used Claude Code as a pair programmer inside guard rails I set up: hooks block deploys, cloud
writes and new dependencies without my approval, the test suite runs at the end of every turn,
and the spec must be approved before code is written. My job was the decisions (scope, service
choices, trade-offs), reviewing the designs and the diffs, and approving anything billed.

### Why write design docs for a solo project?
They record why, which code doesn't. "Why Titan and not Cohere?" has a written answer with the
evidence (an API response, a doc page) and the rejected options. They also force me to check
facts first: AgentCore and S3 Vectors APIs are verified against current AWS docs through an MCP
server before designing.

### How do you handle cloud actions safely during development?
Every deploy, destroy or cloud write needs explicit approval, enforced by a hook rather than
memory. Live checks are always a separate final task group in each change and never part of the
default test run.

---

## 9. Problems hit and lessons

### What surprised you during the build?
- **No `AWS::Budgets::Budget` in eu-north-1.** The deploy failed with `TypeNotFoundException`.
  I kept the budget in IaC by having CDK call the Budgets API through a custom resource. Lesson:
  check resource-type availability per region before designing on it.
- **Cohere Embed v4 wasn't usable for the KB in-region**, so the embedding choice flipped to
  Titan V2 after checking the docs and the model's inference types.
- **`aws login` credentials needed `botocore[crt]`**, found by the first live ingest. Added as a
  dev-only dependency, since in AWS the runtime uses its execution role.
- **Destroy leaves a log group** created by CDK's auto-delete Lambda outside CloudFormation.
  Accepted (~$0), documented, and deleted by hand. The tools stack avoids this for its functions
  by owning their log groups.
- **The roadmap promised Deutschland-Ticket flat rates, the sources don't contain them.** The DB
  document only says those rights follow the Deutschland-Ticket tariff. Rather than hardcode
  numbers the agent couldn't cite, the tool returns "not computable from sources" with that
  clause. Lesson: read the source before promising a rule.
- **A property test caught a spec contradiction.** "Compensation never exceeds 50 % of the price"
  and "round half-up to cents" (DB A.9.2.1) disagree for a €0.01 ticket. Hypothesis found it in
  seconds; the spec now states the bound after rounding.

### What would you do differently or improve next?
Measure retrieval quality with an evaluation set before tuning anything (that's milestone 7):
chunk size and the embedding model are educated guesses until then. If cross-language questions
turn out weak, revisit Cohere through an inference profile. A profile-less AWS client path is
needed for AgentCore Runtime, where there is no `railagent` profile.

### What are the known limitations?
Semantic search only, so exact article numbers ("Art. 19") match by meaning, not keyword. Only
three documents. Train delays come from seeded mock data, not a live DB API. The compensation
rules cover single, return, long-distance season tickets and BahnCard 100; Deutschland-Ticket,
regional season tickets and cumulative caps across a validity period are out of scope. The system
explains rights; it doesn't give legal advice or represent anyone.

---

## 10. Tools and the agent

The tools are built (milestone 3); the agent that calls them is planned. Rewrite each *(planned)*
answer as its milestone lands.

### How do the tools work?
Three plain Python functions in `rail_rights_agent.tools`, each with a thin Lambda handler:
`get_train_delay` reads a mock trip record from DynamoDB, `calculate_compensation` applies the
legal rules with no AWS access at all, and `submit_claim` writes a claim once. Locally the agent
will call the functions in-process; on AgentCore, Gateway will expose the same Lambdas as MCP
tools. One implementation, two transports, so the logic is tested once. The handlers already
take the Gateway's event format (the tool arguments as the event, JSON back), so milestone 5 adds
the Gateway without touching them.

### How do you make sure the model never computes money?
It has no way to: the only path to an amount is `calculate_compensation`, deterministic Python
over `Decimal`. The rules are a table with the clause next to each number (Art. 19(1) 25 %/50 %,
Art. 19(3) half price for return tickets, Art. 19(9) and (10) exclusions, DB A.9.2.1 half-up
rounding and the €4 minimum, DB B.13.1 and C.3.10.1 flat rates). Every result lists those
references by document id and clause, so the model's job is to explain and cite the passage the
knowledge base returns for them. The tests are one case per spec scenario plus Hypothesis
properties: bounded by 50 % after rounding, monotonic in delay, payout is zero or at least €4.

### How does the confirmation token work, and why isn't it a secret?
`calculate_compensation` returns a token: a short SHA-256 digest of the inputs that affect the
amount plus the payout. `submit_claim` recomputes the compensation from the submitted fields and
rejects the claim unless the token matches. So the model cannot submit an amount it made up or a
claim it never had computed. It is deliberately not an HMAC: the callers are my own agent and,
later, the Gateway behind Cognito; the risk is a fabricated number, not an attacker forging
digests, and a secret would mean Secrets Manager and two more IAM grants for no gain. The human
"yes" is the agent's half of the two-phase flow (milestone 4).

### How is claim submission idempotent?
The claim id is derived from the token, so "the same confirmed claim" and "the same id" are the
same thing. The write is a `PutItem` with `attribute_not_exists(claim_id)`; if that condition
fails, the tool reads the existing record and returns it marked `already_submitted`. No
read-before-write race, no second table or index.

### Why one Lambda per tool instead of one function dispatching on the tool name?
Least privilege and simplicity. The delay function can only read the trips table, the submit
function can only get and put claims, and the compensation function has no table access at all;
a single function would need the union. Gateway prefixes tool names with the target name, which
a dispatching function has to strip; one tool per target avoids that. Three small functions also
mean three small blast radii.

### What did the source documents not settle?
Deutschland-Ticket compensation: the DB conditions say (C.3.10.3) that its rights follow the
Deutschland-Ticket tariff, which isn't one of the three source documents and may not be added
casually. The tool returns "not computable from sources" with that reference instead of guessing,
and the same applies to regional season tickets and to cumulative caps over a validity period.
The roadmap had promised Deutschland-Ticket rates; the design records the deviation.

### How will you prevent a claim being submitted without consent? *(agent half planned, milestone 4)*
Two phases: the agent shows a claim summary and waits for an explicit yes, then calls
`submit_claim` with the token from the computation. The tool half is built: without a matching
token nothing is written, and a retry can't file twice. Agent tests with a stubbed model will
assert that `submit_claim` is never called without confirmation.

### What goes in AgentCore Memory versus DynamoDB? *(planned, milestone 5)*
DynamoDB is the single source of truth for claims. Memory holds only preferences and session
summaries. Keeping claims out of Memory avoids two copies drifting apart and keeps personal data
in one place that Guardrails and deletion can reason about.

### How will you know the agent is good? *(planned, milestone 7)*
A golden set of ~40 German and English cases scored on compensation exact match, correct tool
calls, citations present and correct, correct refusals, latency and cost, plus an LLM-as-judge
faithfulness score, reported per model (Haiku vs Nova). CI checks a committed results file on
every PR; the live eval runs only on request, never on fork PRs, because the repo is public.
