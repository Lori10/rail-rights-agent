"""Offline boto3 clients for the knowledge-base tests: botocore Stubber, dummy credentials."""

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

REGION = "eu-north-1"


def _client(service: str) -> Any:
    return boto3.client(
        service,  # type: ignore[call-overload]
        region_name=REGION,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


@pytest.fixture
def runtime_client() -> Any:
    return _client("bedrock-agent-runtime")


@pytest.fixture
def agent_client() -> Any:
    return _client("bedrock-agent")


@pytest.fixture
def s3_client() -> Any:
    return _client("s3")


@pytest.fixture
def cfn_client() -> Any:
    return _client("cloudformation")


def _stubbed(client: Any) -> Iterator[Stubber]:
    with Stubber(client) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


@pytest.fixture
def runtime_stub(runtime_client: Any) -> Iterator[Stubber]:
    yield from _stubbed(runtime_client)


@pytest.fixture
def agent_stub(agent_client: Any) -> Iterator[Stubber]:
    yield from _stubbed(agent_client)


@pytest.fixture
def s3_stub(s3_client: Any) -> Iterator[Stubber]:
    yield from _stubbed(s3_client)


@pytest.fixture
def cfn_stub(cfn_client: Any) -> Iterator[Stubber]:
    yield from _stubbed(cfn_client)
