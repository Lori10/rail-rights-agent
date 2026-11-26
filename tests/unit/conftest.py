"""Offline boto3 clients shared by the unit tests: botocore Stubber, dummy credentials."""

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

REGION = "eu-north-1"


def offline_client(service: str) -> Any:
    return boto3.client(
        service,  # type: ignore[call-overload]
        region_name=REGION,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


@pytest.fixture
def dynamodb_client() -> Any:
    return offline_client("dynamodb")


@pytest.fixture
def dynamodb_stub(dynamodb_client: Any) -> Iterator[Stubber]:
    with Stubber(dynamodb_client) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()
