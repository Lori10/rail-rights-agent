"""Upload the catalogue to the deployed knowledge base and run an ingestion job (design D5, D8).

Every target comes from the deployed stack's outputs; clients, ``sleep`` and ``monotonic`` are
injected so the whole flow is testable offline.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from rail_rights_agent.knowledge_base.catalogue import CATALOGUE, sidecar_json
from rail_rights_agent.knowledge_base.deployment import (
    DOCUMENTS_PREFIX,
    OUTPUT_DATA_SOURCE_ID,
    OUTPUT_DOCUMENTS_BUCKET,
    OUTPUT_KNOWLEDGE_BASE_ID,
    STACK_NAME,
)
from rail_rights_agent.knowledge_base.errors import KnowledgeBaseError

if TYPE_CHECKING:
    from mypy_boto3_bedrock_agent import AgentsforBedrockClient
    from mypy_boto3_cloudformation import CloudFormationClient
    from mypy_boto3_s3 import S3Client

__all__ = [
    "STACK_NAME",
    "IngestionResult",
    "StackOutputs",
    "ingest_catalogue",
    "resolve_stack_outputs",
    "run_ingestion",
    "upload_catalogue",
]

POLL_SECONDS = 10
TIMEOUT_SECONDS = 30 * 60
_TERMINAL = {"COMPLETE", "FAILED", "STOPPED"}


@dataclass(frozen=True)
class StackOutputs:
    knowledge_base_id: str
    data_source_id: str
    documents_bucket: str


@dataclass(frozen=True)
class IngestionResult:
    job_id: str
    status: str
    scanned: int
    indexed: int
    failed: int


def resolve_stack_outputs(
    cfn: "CloudFormationClient", stack_name: str = STACK_NAME
) -> StackOutputs:
    try:
        (stack,) = cfn.describe_stacks(StackName=stack_name)["Stacks"]
    except ClientError as err:
        if "does not exist" in err.response.get("Error", {}).get("Message", ""):
            raise KnowledgeBaseError(
                "StackNotFound",
                f"stack {stack_name} does not exist; deploy first with scripts/deploy.sh",
            ) from err
        raise KnowledgeBaseError.from_client_error(err) from err
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
    keys = (OUTPUT_KNOWLEDGE_BASE_ID, OUTPUT_DATA_SOURCE_ID, OUTPUT_DOCUMENTS_BUCKET)
    missing = [k for k in keys if k not in outputs]
    if missing:
        raise KnowledgeBaseError(
            "StackOutputMissing", f"stack {stack_name} has no output {', '.join(missing)}"
        )
    return StackOutputs(
        knowledge_base_id=outputs[OUTPUT_KNOWLEDGE_BASE_ID],
        data_source_id=outputs[OUTPUT_DATA_SOURCE_ID],
        documents_bucket=outputs[OUTPUT_DOCUMENTS_BUCKET],
    )


def _check_sources(source_dir: Path) -> None:
    missing = [d.filename for d in CATALOGUE if not (source_dir / d.filename).is_file()]
    if missing:
        raise KnowledgeBaseError(
            "MissingSourceDocument", f"{', '.join(missing)} not found in {source_dir}"
        )


def upload_catalogue(s3: "S3Client", bucket: str, source_dir: Path) -> list[str]:
    """Upload every catalogued PDF and its metadata sidecar; returns the uploaded keys."""
    _check_sources(source_dir)
    keys: list[str] = []
    try:
        for doc in CATALOGUE:
            key = f"{DOCUMENTS_PREFIX}{doc.filename}"
            body = (source_dir / doc.filename).read_bytes()
            s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/pdf")
            s3.put_object(
                Bucket=bucket,
                Key=f"{key}.metadata.json",
                Body=sidecar_json(doc),
                ContentType="application/json",
            )
            keys += [key, f"{key}.metadata.json"]
    except ClientError as err:
        raise KnowledgeBaseError.from_client_error(err) from err
    return keys


def run_ingestion(
    agent: "AgentsforBedrockClient",
    knowledge_base_id: str,
    data_source_id: str,
    *,
    poll_seconds: float = POLL_SECONDS,
    timeout_seconds: float = TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> IngestionResult:
    """Start an ingestion job and wait for it; raise unless it completes with no failed docs."""
    ids = {"knowledgeBaseId": knowledge_base_id, "dataSourceId": data_source_id}
    try:
        job_id = agent.start_ingestion_job(**ids)["ingestionJob"]["ingestionJobId"]
        deadline = monotonic() + timeout_seconds
        while True:
            job = agent.get_ingestion_job(**ids, ingestionJobId=job_id)["ingestionJob"]
            if job["status"] in _TERMINAL:
                break
            if monotonic() + poll_seconds > deadline:
                raise KnowledgeBaseError(
                    "IngestionTimeout",
                    f"job {job_id} still {job['status']} after {timeout_seconds:.0f} s",
                )
            sleep(poll_seconds)
    except ClientError as err:
        raise KnowledgeBaseError.from_client_error(err) from err

    if job["status"] != "COMPLETE":
        reasons = "; ".join(job.get("failureReasons", [])) or "no reason given"
        raise KnowledgeBaseError("IngestionFailed", f"job {job_id} {job['status']}: {reasons}")
    stats = job.get("statistics", {})
    result = IngestionResult(
        job_id=job_id,
        status=job["status"],
        scanned=stats.get("numberOfDocumentsScanned", 0),
        indexed=stats.get("numberOfNewDocumentsIndexed", 0)
        + stats.get("numberOfModifiedDocumentsIndexed", 0),
        failed=stats.get("numberOfDocumentsFailed", 0),
    )
    if result.failed:
        raise KnowledgeBaseError(
            "IngestionIncomplete",
            f"job {job_id}: {result.failed} failed of {result.scanned} scanned",
        )
    return result


def ingest_catalogue(
    cfn: "CloudFormationClient",
    s3: "S3Client",
    agent: "AgentsforBedrockClient",
    source_dir: Path,
    *,
    stack_name: str = STACK_NAME,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> IngestionResult:
    """Check the sources, find the stack, upload, then ingest. No AWS call if a file is missing."""
    _check_sources(source_dir)
    outputs = resolve_stack_outputs(cfn, stack_name)
    upload_catalogue(s3, outputs.documents_bucket, source_dir)
    return run_ingestion(
        agent,
        outputs.knowledge_base_id,
        outputs.data_source_id,
        sleep=sleep,
        monotonic=monotonic,
    )
