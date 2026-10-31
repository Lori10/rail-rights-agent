# Design

## Context

Foundation left us with:
- a CDK app (`infra/app.py::build_app`) whose stacks are tagged by `apply_project_tags`
- a test that walks every synthesised resource and checks its tags (it reads both list and map `Tags`)
- one-command `scripts/deploy.sh` / `destroy.sh`
- typed settings with `RAILAGENT_EMBEDDING_MODEL_ID`
- a source scan that allows Bedrock model ids only in `settings.py`

The three source PDFs (about 3.3 MB) are in `docs/source/`. That folder is gitignored, so it doesn't exist in CI.

**Verified against AWS docs (aws-docs MCP, 2026-10-31) and read-only API calls in eu-north-1:**
- **CloudFormation types:** `AWS::S3Vectors::VectorBucket`, `AWS::S3Vectors::Index`, `AWS::Bedrock::KnowledgeBase` and `AWS::Bedrock::DataSource` all exist in eu-north-1. aws-cdk-lib 2.275 has the L1s: `aws_s3vectors.CfnVectorBucket`/`CfnIndex`, and `aws_bedrock.CfnKnowledgeBase` with `S3VectorsConfigurationProperty`.
- **S3 Vectors with Knowledge Bases:**
  - float32 only
  - semantic search only, no hybrid search
  - filterable metadata of 2 KB per vector, 40 KB total
  - at most 10 non-filterable keys per index, which can't be changed after creation
- **Embedding models for Knowledge Bases:** the in-region list for eu-north-1 contains only Titan Text Embeddings V2 (256/512/1024 dimensions). `cohere.embed-v4:0` reports `inferenceTypesSupported: [INFERENCE_PROFILE]` in eu-north-1, so it is reachable only through `eu.`/`global.` profiles.
- **Service-role permissions:**
  - `bedrock:InvokeModel` on the embedding model
  - `s3vectors:PutVectors/GetVectors/DeleteVectors/QueryVectors/GetIndex` on the index ARN
  - S3 read on the data source
  - trust to `bedrock.amazonaws.com`, conditioned on `aws:SourceAccount` and the knowledge-base ARN

## Goals / Non-Goals

**Goals:**
- `scripts/deploy.sh`, then the ingest command, gives a queryable knowledge base. `scripts/destroy.sh` removes everything, including stored documents and vectors.
- One retrieval function that the agent (milestone 4) and the eval harness (milestone 7) can call, with the citation fields they need.
- Fully offline tests: synth assertions plus botocore `Stubber` tests.

**Non-Goals:**
- Answer generation (`RetrieveAndGenerate`): the agent generates and cites.
- Reranking, hybrid search, query rewriting. S3 Vectors has no hybrid search; reranking can be reconsidered in `evaluation` if retrieval quality is short.
- Automatic re-ingestion on document change. The corpus is three fixed PDFs, so ingestion is run by hand.
- Exposing retrieval as a Gateway/MCP tool: that is `agentcore`.

## Decisions

### D1. One `KnowledgeBaseStack`, always deployed
- **Choice:**
  - `infra/stacks/knowledge_base.py::KnowledgeBaseStack`, created in `build_app` as `RailRightsAgent-KnowledgeBase`. It takes the embedding model id from settings.
  - The stack holds the documents bucket, the vector bucket and index, the service role, the knowledge base and the data source.
  - Outputs: `KnowledgeBaseId`, `DataSourceId`, `DocumentsBucketName`.
- **Why:** These resources are created and destroyed together, and the stack has no idle compute.
- **Rejected:**
  - Adding the resources to `BaselineStack`: the baseline stays an empty anchor.
  - An opt-in stack like the budget: every later milestone needs the knowledge base, so making it optional only adds a flag.

### D2. Embedding model: Titan Text Embeddings V2, 1024 dimensions, float32
- **Choice:** Default `RAILAGENT_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0`. The knowledge base's embedding ARN is `arn:aws:bedrock:<region>::foundation-model/<id>`, with `BedrockEmbeddingModelConfiguration(dimensions=1024, embedding_data_type="FLOAT32")`. The dimension is a constant in the stack module, next to the index.
- **Why:**
  - It's the only Knowledge Base embedding model the docs list in-region for eu-north-1.
  - It's multilingual (100+ languages, German included).
  - 1024 is its highest-quality dimension, and storage is negligible at this corpus size.
  - It costs $0.00002 per 1K tokens.
- **Rejected:**
  - **Cohere Embed v4.** In eu-north-1 it is reachable only through a cross-region profile, and it isn't in the Knowledge Base embedding-model list. A knowledge base on an inference-profile embedding ARN is documented only for TwelveLabs Marengo. It would also need IAM on the foundation model in six EU regions. Too much risk for a deploy to discover.
  - **Cohere Embed Multilingual v3.** Not offered in eu-north-1 (`GetFoundationModel` returns `ValidationException`).
  - **Titan V2 at 512 or 256 dimensions.** These save almost nothing at this size and retrieve less well.
- **Coupling:** if the embedding id is overridden, the 1024 dimension must still fit. Titan V2 at 1024 is the only supported value in this design. Any other model needs a design change, not just an environment variable. This is recorded as a risk.

### D3. Vector store: L1 S3 Vectors bucket and index, Bedrock keys non-filterable
- **Choice:**
  - `CfnVectorBucket` with a generated name and default SSE-S3.
  - `CfnIndex` with `data_type="float32"`, `dimension=1024`, `distance_metric="cosine"`, a generated name, and `metadata_configuration.non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]`.
  - The knowledge base references the index by `index_arn` (the `Ref` of `CfnIndex`).
- **Why:**
  - The knowledge base writes chunk text and its own metadata into these two keys, and a 300-token chunk alone exceeds the 2 KB filterable limit.
  - Our sidecar attributes (`document`, `language`) stay filterable, which the language filter needs.
  - Cosine is the usual metric for Titan's normalised embeddings.
  - Generated names allow replacement, because every index property requires replacement.
- **Rejected:**
  - Console "quick create": not IaC.
  - OpenSearch Serverless: idle cost, and forbidden by CLAUDE.md.
  - A hand-written custom resource over the S3 Vectors API: the CloudFormation types exist in eu-north-1.

### D4. Chunking: fixed size, 300 tokens, 20 % overlap; default parser
- **Choice:**
  - `ChunkingConfiguration(chunking_strategy="FIXED_SIZE", fixed_size_chunking_configuration=(max_tokens=300, overlap_percentage=20))`
  - the default (non-FM) parser
  - `data_deletion_policy="DELETE"`, so removing the data source removes its vectors
- **Why:**
  - The articles in 2021/782 and the DB clauses are short. 300 tokens holds an article paragraph with room to spare.
  - 20 % overlap keeps a sentence that spans two chunks retrievable.
  - These are the service defaults, so results are easy to compare later.
  - The default parser extracts text from these text-based PDFs at no model cost.
- **Rejected:**
  - **Hierarchical chunking.** The docs warn that parent/child context is stored as non-filterable metadata and can exceed S3 Vectors limits.
  - **Semantic chunking.** It costs embedding calls at ingestion and gives less predictable chunk sizes. It can be revisited if `evaluation` shows split articles.
  - **FM parsing (Claude/Nova).** Billed inference per page. The PDFs have little that needs layout understanding.
- All chunking properties require replacement, so changing them later means a new data source and re-ingestion. This is acceptable for three PDFs.

### D5. Documents are uploaded by the ingest command, not by CDK
- **Choice:**
  - CDK creates the documents bucket: `BlockPublicAccess.BLOCK_ALL`, SSE-S3, `enforce_ssl=True`, `removal_policy=DESTROY`, `auto_delete_objects=True`.
  - The data source reads the `documents/` prefix.
  - The ingest command uploads each catalogued PDF and its sidecar (D6) to `documents/`, then starts the job.
- **Why:**
  - `docs/source/` is gitignored. A CDK `BucketDeployment` asset would make synthesis fail in CI and in the offline tests, unless it were made conditional, and then a deploy without the folder would silently empty the bucket.
  - The sidecars are generated from the catalogue in code, which is easier to keep in the ingestion path.
- **Rejected:**
  - `BucketDeployment` (the roadmap's "uploaded by CDK"), for the reason above.
  - Emptying the bucket in `destroy.sh` instead of `auto_delete_objects`: more shell logic for the same effect.
- **Trade-off:** the auto-delete custom resource's Lambda writes to a log group that CloudFormation doesn't manage. See Risks.

### D6. Document catalogue and metadata sidecars
- **Choice:** `rail_rights_agent/knowledge_base/catalogue.py` holds the three spec entries as frozen dataclasses (`filename`, `document`, `language`, `title`). For each one, ingestion uploads `documents/<filename>` and `documents/<filename>.metadata.json` containing `{"metadataAttributes": {"document": "...", "language": "..."}}`. That is the Knowledge Base sidecar format for S3 data sources.
- **Why:**
  - One source of truth for which files are expected, used by both the missing-file check and the citation fields.
  - The `language` attribute makes the `de`/`en` filter a server-side metadata filter, so the top-k results are all in the requested language.
- **Rejected:**
  - Deriving the language from the filename at query time: it can't be used as a server-side filter.
  - Uploading every file in `docs/source/`: a stray file would enter the knowledge base unnoticed.

### D7. Service role: one role, scoped per resource
- **Choice:** An `iam.Role` assumed by `bedrock.amazonaws.com`, with conditions `aws:SourceAccount=<account>` and `ArnLike aws:SourceArn=arn:aws:bedrock:<region>:<account>:knowledge-base/*`. Inline statements:
  - `bedrock:InvokeModel` on the embedding foundation-model ARN
  - `s3:ListBucket` on the documents bucket, `s3:GetObject` on `documents/*`
  - `s3vectors:PutVectors, GetVectors, DeleteVectors, QueryVectors, GetIndex` on the index ARN

  The knowledge base gets an explicit dependency on the role's policy. Without it, CloudFormation can create the knowledge base before the policy is attached, and the knowledge base's validation of the index fails.
- **Rejected:**
  - Letting Bedrock create the role: not IaC, and too broad.
  - A wildcard on `knowledge-base/<id>`: the id isn't known before creation (circular dependency). `knowledge-base/*` together with the account condition is what the docs recommend.

### D8. Python module layout and CLI
- **Choice:** package `rail_rights_agent.knowledge_base`:
  - `catalogue.py`: D6.
  - `errors.py`: `KnowledgeBaseError(code, message)`.
  - `retrieval.py`:
    - `Passage` frozen dataclass: `text`, `document`, `language`, `source_uri`, `score`, `page: int | None`.
    - `KnowledgeBaseRetriever(client, knowledge_base_id)` with `.retrieve(question, *, language=None, top_k=5) -> list[Passage]`.
    - It validates first, then calls `Retrieve` with `vectorSearchConfiguration.numberOfResults=top_k`, plus `filter={"equals": {"key": "language", "value": language}}` when a language is given.
    - It maps `content.text`, `location.s3Location.uri`, `score`, `metadata.document`, `metadata.language`, and `metadata["x-amz-bedrock-kb-document-page-number"]` when present.
  - `ingest.py`: `resolve_stack_outputs(cfn_client, stack_name)`, `upload_catalogue(s3_client, bucket, source_dir)`, `run_ingestion(agent_client, kb_id, ds_id, *, poll_seconds=10, timeout_seconds=1800, sleep=time.sleep)`.
  - `aws.py`: `clients(settings)`, which builds the boto3 clients from `boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)`.
  - `__main__.py`: argparse with `ingest [--source-dir docs/source]` and `retrieve QUESTION [--language de|en] [--top-k N]`, which prints passages as numbered blocks.

  Clients and `sleep` are injected, so tests drive everything with botocore `Stubber` and a fake sleep.
- **Why:**
  - The agent imports `KnowledgeBaseRetriever` directly.
  - The CLI is the ingestion command and gives a manual retrieval probe for the live checks.
  - Dependency injection keeps the tests offline without `moto`.
- **Rejected:**
  - Bash wrappers in `scripts/`: the logic needs tests. `python -m` is the command, and the README documents it.
  - Putting the knowledge base id in settings: it's a deployment output, not configuration. Milestone 4 decides how the agent receives it, either from the stack output or an environment variable.

### D9. Error wrapping
- **Choice:** Every `botocore.exceptions.ClientError` from S3, CloudFormation or Bedrock calls is re-raised as `KnowledgeBaseError(code, message)` with `from`. A missing stack (`ValidationException` "does not exist" from `DescribeStacks`) becomes a `KnowledgeBaseError` that says "deploy first". The CLI turns `KnowledgeBaseError` into a one-line message and exit 1.
- **Why:** Callers (agent, eval harness) handle one exception type, and the spec's error scenarios become testable.

### D10. Dependencies
- **Choice:**
  - `boto3` as the first `[project.dependencies]` entry, floored at the current release when added.
  - `boto3-stubs[bedrock-agent,bedrock-agent-runtime,cloudformation,s3]` in the `dev` group.
  - Both need user approval.
- **Rejected:**
  - `moto`: botocore's `Stubber` is enough for request/response tests, and it adds no dependency.
  - Untyped boto3 calls behind `# type: ignore`: this defeats strict mypy on the module that maps external responses.

### D11. Tests
- **Infra:** `tests/infra/test_knowledge_base_stack.py` checks the stack properties in the spec (bucket hardening, index settings and non-filterable keys, embedding ARN and dimensions, chunking, role statements, outputs) and that no `AWS::OpenSearchServerless::*` resource exists in any stack. It shares the module-scoped synth fixture pattern.
- **Unit:** `tests/unit/knowledge_base/` covers the catalogue, upload (missing file means no upload), polling (complete, failed, failed-docs, timeout), stack-output resolution (present, missing stack) and retrieval (mapping, ordering, empty, language filter, validation, error wrapping). All of it uses `Stubber`.
- **Spec-driven edit:** `tests/unit/test_settings.py::test_defaults_when_no_overrides` changes its expected embedding id. The `project-configuration` spec changed, so this is allowed. `.env.example` changes with it.
- **Live:** `tests/live/test_knowledge_base_live.py` with `@pytest.mark.live`, one test per spec scenario. It resolves the knowledge base from the stack outputs. Assertions match keywords such as `25`/`50` and `Erstattung`/`refund|reimburse`, never exact text.

### D12. aws-docs MCP server pinned in the project
- **Choice:** `.mcp.json` runs `uvx awslabs.aws-documentation-mcp-server@1.2.3`. That release is from 2026-10-13; 1.2.4 was a day old when this change began.
- **Why:** CLAUDE.md requires verifying AgentCore and S3 Vectors APIs against current docs. Pinning makes the tool reproducible for later milestones.

## Risks / Trade-offs

- **Titan V2 cross-lingual matching is weaker than Cohere's.** An English question may rank German chunks poorly, and the reverse. → The language filter lets the agent query in the user's language. The live test asks each language in its own language. If quality is short, `evaluation` can revisit (for example, Cohere through an inference profile, after checking the docs and the SCP).
- **German compounds and legal phrasing** (Fahrpreisentschädigung, Erstattung) may embed far from colloquial questions. → The live scenarios use natural questions, and failures are recorded here rather than tuned away.
- **The page number may be missing.** The `x-amz-bedrock-kb-document-page-number` key isn't clearly documented for S3 Vectors with the default parser. → `page` is optional in the spec and in `Passage`. The live check records whether it appears.
- **Embedding id overrides and dimension coupling (D2).** Overriding the model to one with a different dimension breaks ingestion. → The constant sits beside the index with a comment. Changing the model is a design change.
- **Creation order.** The knowledge base checks the index and role permissions at creation. → There is an explicit dependency on the role policy (D7). If the first deploy still fails, the cause is recorded here.
- **Deletion order.** CloudFormation must delete the data source, then the knowledge base, then the index, then the vector bucket. The `Ref` dependencies give that order. → The live destroy check confirms that no vector bucket remains (`aws s3vectors list-vector-buckets`).
- **Leftover log group.** The `auto_delete_objects` Lambda creates `/aws/lambda/...CustomS3AutoDeleteObjects...` outside CloudFormation. It holds a few KB, is untagged, and survives destroy. → Accepted (about $0). The live destroy check lists it, and it is recorded here. The AwsCustomResource log-group fix from foundation D7 isn't available for this construct.
- **Ingestion is asynchronous and slow** (minutes). → Poll every 10 s with a 30-minute timeout. A timeout exits non-zero and gives the job id.
- **New, fast-changing services.** S3 Vectors and the Knowledge Base S3 Vectors storage are recent. → APIs were verified 2026-10-31. Any deploy surprise is recorded here with the fix.

- **Known gaps and adjustments found while implementing (offline groups):**
  - `rail_rights_agent/knowledge_base/deployment.py` was added (not listed in D8). It holds the stack name, output keys and the `documents/` prefix, which both `infra/` and the ingest command use, so they can't drift apart.
  - `validate_request` was moved out of `KnowledgeBaseRetriever.retrieve`, so the CLI rejects an empty question before it builds clients or reads the stack. It makes no AWS call at all.
  - boto3-stubs types a metadata filter's `value` as a JSON object, but the API accepts any JSON value. `retrieval.py` uses one commented `cast` for the language string.
  - Each CLI command builds a `boto3.Session` from the `railagent` profile. Running in AgentCore Runtime (milestone 5) has no profile, so `aws.clients` will need a profile-less path there.

## Migration Plan

- Offline groups change nothing in AWS.
- **Live group, each step with your go-ahead:**
  1. `scripts/deploy.sh`: creates the knowledge-base stack. Baseline is unchanged, and the budget stack too if the email is set.
  2. `uv run python -m rail_rights_agent.knowledge_base ingest`.
  3. `uv run pytest -m live tests/live/test_knowledge_base_live.py`.
  4. `scripts/destroy.sh`. Check that no stack, documents bucket or vector bucket remains.
  5. Redeploy and re-ingest, and leave it running for `agent-local` (storage cents per month). Optional: your call.
- **Rollback:** `scripts/destroy.sh`, or revert the branch. Nothing else depends on the knowledge base yet.
