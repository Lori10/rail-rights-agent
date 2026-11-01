# Proposal

## Why

The agent must cite retrieved passages from EU Regulation 2021/782 (EN and DE) and the DB conditions of carriage for every answer about rights. Nothing can be retrieved yet. This change builds the knowledge base that the `agent-local` milestone (roadmap #4) will query.

## What Changes

- A new `RailRightsAgent-KnowledgeBase` stack with:
  - a private S3 bucket for the source documents
  - an S3 Vectors vector bucket and index
  - a Bedrock Knowledge Base (vector type, S3 Vectors storage)
  - an S3 data source with fixed-size chunking
  - a least-privilege service role
  - stack outputs for the knowledge base id, data source id and documents bucket

  It is deployed and destroyed with the existing one-command scripts.
- An ingestion command. It uploads the three catalogued source documents from `docs/source/`, each with a metadata sidecar giving its document id and language. It then starts an ingestion job, waits for it to finish, and reports scanned, indexed and failed counts.
- A retrieval client in `src/rail_rights_agent/`. It returns ranked passages with text, document id, language, source URI, page (when present) and score. It can filter by language, and it rejects invalid input before calling AWS.
- **Embedding model changes from Cohere Embed v4 to Amazon Titan Text Embeddings V2** (`amazon.titan-embed-text-v2:0`, 1024 dimensions). The AWS docs, checked 2026-10-31, show:
  - Knowledge Bases support Titan V2 in-region in eu-north-1.
  - Cohere Embed v4 is reachable in eu-north-1 only through the `eu.`/`global.` inference profiles, and the Knowledge Base embedding-model list doesn't include it.

  Titan V2 is multilingual (German included) and about 6× cheaper. The roadmap leaned towards Cohere; this proposal changes that. Details are in design.md D2.
- A live smoke test (`@pytest.mark.live`, excluded by default). It asks about 60/120-minute delay compensation and refunds (Erstattung) in German and English, and checks that the expected passages come back.
- The project's aws-docs MCP server is pinned in `.mcp.json` (aws-documentation-mcp-server 1.2.3). It was used to verify the S3 Vectors and Knowledge Base APIs for this change.

## Capabilities

### New Capabilities
- `knowledge-base`: the rights-document knowledge base. It covers which documents it holds, how they are ingested, and how passages are retrieved with source attribution for citations.

### Modified Capabilities
- `project-configuration`: the default embedding model in "Defaults match the project's AWS environment" changes from `cohere.embed-v4:0` to `amazon.titan-embed-text-v2:0`.

## Impact

- **Code:**
  - new `infra/stacks/knowledge_base.py`, wired into `infra/app.py`
  - new `src/rail_rights_agent/knowledge_base/`, holding the document catalogue, ingestion and retrieval
  - the default in `settings.py` and `.env.example`
  - tests under `tests/unit/` and `tests/infra/`, and a new `tests/live/`
  - the README development section, which gains the ingest step
- **New dependencies (need your approval):**
  - `boto3`, a runtime dependency, for the ingestion command and the retrieval client. It is the AWS SDK, so later milestones need it anyway.
  - `boto3-stubs[bedrock-agent,bedrock-agent-runtime,cloudformation,s3]`, in the dev group, so strict mypy can type-check the boto3 calls.

  Offline tests use botocore's built-in `Stubber`, so no `moto`. The CDK constructs (`aws_s3vectors`, `aws_bedrock` L1) are already in aws-cdk-lib 2.275.
- **Live and billed resources:** these are created only in the final live task group, with your go-ahead for each step. All costs below are pay-per-use, with no idle cost beyond storage cents.
  - S3 bucket holding about 3.3 MB of PDFs: under $0.01/month.
  - S3 Vectors storage, a few thousand 1024-dim vectors (about 10–20 MB): under $0.01/month. Writes and queries: cents.
  - Bedrock Knowledge Base: no charge of its own.
  - Titan V2 embeddings: the documents are a few hundred thousand tokens at $0.00002 per 1K tokens, about $0.01 per full ingestion. Each query embedding is negligible.
  - CDK auto-delete Lambda for the documents bucket: runs only at destroy, about $0.
  - **Estimated total for this milestone: under $0.25,** including a few re-ingestions and smoke runs. The roadmap estimated under $0.50.
- **Not touched:** no OpenSearch Serverless, no models besides the embedding model, and no changes to the budget or baseline stacks.
