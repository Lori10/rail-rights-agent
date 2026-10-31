"""Spec: knowledge-base / ingestion requirements (catalogue upload, job outcome, stack outputs)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from botocore.stub import Stubber

from rail_rights_agent.knowledge_base.catalogue import CATALOGUE, sidecar_json
from rail_rights_agent.knowledge_base.errors import KnowledgeBaseError
from rail_rights_agent.knowledge_base.ingest import (
    STACK_NAME,
    StackOutputs,
    ingest_catalogue,
    resolve_stack_outputs,
    run_ingestion,
    upload_catalogue,
)

KB_ID = "KB12345678"
DS_ID = "DS12345678"
BUCKET = "railrightsagent-documents-abc"
JOB_ID = "JOB1234567"
NOW = datetime(2026, 10, 31, tzinfo=UTC)
OUTPUTS = StackOutputs(knowledge_base_id=KB_ID, data_source_id=DS_ID, documents_bucket=BUCKET)


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    for doc in CATALOGUE:
        (tmp_path / doc.filename).write_bytes(f"%PDF-fake {doc.filename}".encode())
    return tmp_path


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def job(status: str, **extra: Any) -> dict[str, Any]:
    return {
        "ingestionJob": {
            "knowledgeBaseId": KB_ID,
            "dataSourceId": DS_ID,
            "ingestionJobId": JOB_ID,
            "status": status,
            "startedAt": NOW,
            "updatedAt": NOW,
            **extra,
        }
    }


def stats(scanned: int = 3, new: int = 3, modified: int = 0, failed: int = 0) -> dict[str, int]:
    return {
        "numberOfDocumentsScanned": scanned,
        "numberOfNewDocumentsIndexed": new,
        "numberOfModifiedDocumentsIndexed": modified,
        "numberOfDocumentsFailed": failed,
    }


def expect_job(agent_stub: Stubber, *statuses: dict[str, Any]) -> None:
    agent_stub.add_response(
        "start_ingestion_job",
        job("STARTING"),
        {"knowledgeBaseId": KB_ID, "dataSourceId": DS_ID},
    )
    for response in statuses:
        agent_stub.add_response(
            "get_ingestion_job",
            response,
            {"knowledgeBaseId": KB_ID, "dataSourceId": DS_ID, "ingestionJobId": JOB_ID},
        )


def expect_uploads(s3_stub: Stubber, source_dir: Path) -> None:
    for doc in CATALOGUE:
        s3_stub.add_response(
            "put_object",
            {},
            {
                "Bucket": BUCKET,
                "Key": f"documents/{doc.filename}",
                "Body": (source_dir / doc.filename).read_bytes(),
                "ContentType": "application/pdf",
            },
        )
        s3_stub.add_response(
            "put_object",
            {},
            {
                "Bucket": BUCKET,
                "Key": f"documents/{doc.filename}.metadata.json",
                "Body": sidecar_json(doc),
                "ContentType": "application/json",
            },
        )


def expect_stack(cfn_stub: Stubber) -> None:
    cfn_stub.add_response(
        "describe_stacks",
        {
            "Stacks": [
                {
                    "StackName": STACK_NAME,
                    "CreationTime": NOW,
                    "StackStatus": "CREATE_COMPLETE",
                    "Outputs": [
                        {"OutputKey": "KnowledgeBaseId", "OutputValue": KB_ID},
                        {"OutputKey": "DataSourceId", "OutputValue": DS_ID},
                        {"OutputKey": "DocumentsBucketName", "OutputValue": BUCKET},
                    ],
                }
            ]
        },
        {"StackName": STACK_NAME},
    )


# --- Catalogue upload ---------------------------------------------------------------------------


def test_upload_sends_each_document_with_its_sidecar(s3_client, s3_stub, source_dir):
    expect_uploads(s3_stub, source_dir)
    keys = upload_catalogue(s3_client, BUCKET, source_dir)
    assert len(keys) == 2 * len(CATALOGUE)


def test_missing_file_uploads_nothing_and_starts_no_job(
    cfn_client, cfn_stub, s3_client, s3_stub, agent_client, agent_stub, source_dir
):
    missing = CATALOGUE[1].filename
    (source_dir / missing).unlink()
    with pytest.raises(KnowledgeBaseError, match=missing):
        ingest_catalogue(cfn_client, s3_client, agent_client, source_dir)
    # No responses were queued: any AWS call would have raised a stub error instead.


# --- Ingestion job outcome ----------------------------------------------------------------------


def test_job_completes_cleanly_and_reports_counts(agent_client, agent_stub):
    clock = FakeClock()
    expect_job(agent_stub, job("IN_PROGRESS"), job("COMPLETE", statistics=stats()))
    result = run_ingestion(agent_client, KB_ID, DS_ID, sleep=clock.sleep, monotonic=clock.monotonic)
    assert (result.job_id, result.status) == (JOB_ID, "COMPLETE")
    assert (result.scanned, result.indexed, result.failed) == (3, 3, 0)
    assert clock.sleeps  # it waited between polls


def test_indexed_counts_new_and_modified_documents(agent_client, agent_stub):
    clock = FakeClock()
    expect_job(agent_stub, job("COMPLETE", statistics=stats(new=1, modified=2)))
    result = run_ingestion(agent_client, KB_ID, DS_ID, sleep=clock.sleep, monotonic=clock.monotonic)
    assert result.indexed == 3


def test_failed_job_raises_with_service_reasons(agent_client, agent_stub):
    clock = FakeClock()
    expect_job(agent_stub, job("FAILED", failureReasons=["Embedding model access denied"]))
    with pytest.raises(KnowledgeBaseError, match="Embedding model access denied"):
        run_ingestion(agent_client, KB_ID, DS_ID, sleep=clock.sleep, monotonic=clock.monotonic)


def test_failed_documents_raise_with_failed_count(agent_client, agent_stub):
    clock = FakeClock()
    expect_job(agent_stub, job("COMPLETE", statistics=stats(new=2, failed=1)))
    with pytest.raises(KnowledgeBaseError, match=r"1 failed"):
        run_ingestion(agent_client, KB_ID, DS_ID, sleep=clock.sleep, monotonic=clock.monotonic)


def test_poll_timeout_raises_with_job_id(agent_client, agent_stub):
    clock = FakeClock()
    expect_job(agent_stub, job("IN_PROGRESS"), job("IN_PROGRESS"), job("IN_PROGRESS"))
    with pytest.raises(KnowledgeBaseError, match=JOB_ID):
        run_ingestion(
            agent_client,
            KB_ID,
            DS_ID,
            poll_seconds=10,
            timeout_seconds=25,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )


def test_start_error_is_wrapped_with_its_code(agent_client, agent_stub):
    agent_stub.add_client_error(
        "start_ingestion_job",
        service_error_code="ConflictException",
        service_message="An ingestion job is already running",
        http_status_code=409,
    )
    with pytest.raises(KnowledgeBaseError, match="ConflictException") as err:
        run_ingestion(agent_client, KB_ID, DS_ID, sleep=lambda _: None)
    assert err.value.code == "ConflictException"


# --- Stack outputs ------------------------------------------------------------------------------


def test_stack_outputs_resolved_from_deployed_stack(cfn_client, cfn_stub):
    expect_stack(cfn_stub)
    assert resolve_stack_outputs(cfn_client) == OUTPUTS


def test_missing_stack_says_deploy_first(cfn_client, cfn_stub):
    cfn_stub.add_client_error(
        "describe_stacks",
        service_error_code="ValidationError",
        service_message=f"Stack with id {STACK_NAME} does not exist",
        http_status_code=400,
    )
    with pytest.raises(KnowledgeBaseError, match="deploy"):
        resolve_stack_outputs(cfn_client)


def test_ingest_catalogue_targets_the_deployed_stack(
    cfn_client, cfn_stub, s3_client, s3_stub, agent_client, agent_stub, source_dir
):
    clock = FakeClock()
    expect_stack(cfn_stub)
    expect_uploads(s3_stub, source_dir)
    expect_job(agent_stub, job("COMPLETE", statistics=stats()))
    result = ingest_catalogue(
        cfn_client,
        s3_client,
        agent_client,
        source_dir,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result.status == "COMPLETE"
