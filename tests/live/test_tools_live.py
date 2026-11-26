"""Spec: tool-functions / Live tools behave end to end.

Live and billed (Lambda invocations, DynamoDB requests): run only with ``pytest -m live`` against
a deployed and seeded tools stack, with fresh ``railagent`` credentials.
"""

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from rail_rights_agent.aws import session, stack_outputs
from rail_rights_agent.settings import load_settings
from rail_rights_agent.tools.deployment import (
    OUTPUT_CALCULATE_COMPENSATION_FUNCTION_ARN,
    OUTPUT_GET_TRAIN_DELAY_FUNCTION_ARN,
    OUTPUT_SUBMIT_CLAIM_FUNCTION_ARN,
    STACK_NAME,
)

if TYPE_CHECKING:
    from mypy_boto3_lambda import LambdaClient

pytestmark = pytest.mark.live

FUNCTION_KEYS = (
    OUTPUT_GET_TRAIN_DELAY_FUNCTION_ARN,
    OUTPUT_CALCULATE_COMPENSATION_FUNCTION_ARN,
    OUTPUT_SUBMIT_CLAIM_FUNCTION_ARN,
)


class Tools:
    def __init__(self, client: "LambdaClient", arns: dict[str, str]) -> None:
        self.client = client
        self.arns = arns

    def call(self, key: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self.client.invoke(FunctionName=self.arns[key], Payload=json.dumps(arguments))
        assert "FunctionError" not in response, response
        result: dict[str, Any] = json.loads(response["Payload"].read())
        return result


@pytest.fixture(scope="module")
def tools() -> Tools:
    aws = session(load_settings())
    arns = stack_outputs(aws.client("cloudformation"), STACK_NAME, FUNCTION_KEYS)
    return Tools(aws.client("lambda"), arns)


def test_live_round_trip(tools: Tools):
    trip = tools.call(
        OUTPUT_GET_TRAIN_DELAY_FUNCTION_ARN,
        {"train_number": "ICE 123", "travel_date": "2026-11-20"},
    )
    assert "error" not in trip, trip
    assert trip["delay_minutes"] == 120

    compensation = tools.call(
        OUTPUT_CALCULATE_COMPENSATION_FUNCTION_ARN,
        {
            "ticket_price_eur": "100",
            "delay_minutes": trip["delay_minutes"],
            "ticket_kind": "single",
            "cause": trip["cause"],
        },
    )
    assert "error" not in compensation, compensation
    assert Decimal(compensation["payout_eur"]) == Decimal("50.00")
    token = compensation["confirmation_token"]
    assert token

    claim = {
        "train_number": "ICE 123",
        "travel_date": "2026-11-20",
        "ticket_price_eur": "100",
        "delay_minutes": trip["delay_minutes"],
        "ticket_kind": "single",
        "cause": trip["cause"],
        "passenger_name": "Live Test",
        "email": "live-test@example.com",
        "confirmation_token": token,
    }
    first = tools.call(OUTPUT_SUBMIT_CLAIM_FUNCTION_ARN, claim)
    assert "error" not in first, first
    assert first["claim_id"].startswith("CLM-")
    assert Decimal(first["payout_eur"]) == Decimal("50.00")

    second = tools.call(OUTPUT_SUBMIT_CLAIM_FUNCTION_ARN, claim)
    assert "error" not in second, second
    assert second["claim_id"] == first["claim_id"]
    assert second["already_submitted"] is True
    assert second["submitted_at"] == first["submitted_at"]
