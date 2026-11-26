"""Spec: tool-functions (handlers: arguments in, JSON out, errors as data)."""

import json
from decimal import Decimal
from typing import Any

import pytest

from rail_rights_agent.tools import handlers
from rail_rights_agent.tools.compensation import (
    CompensationRequest,
    calculate_compensation,
)
from rail_rights_agent.tools.delays import trip_to_item
from rail_rights_agent.tools.deployment import ENV_CLAIMS_TABLE, ENV_TRIPS_TABLE
from rail_rights_agent.tools.seed_data import SEED_TRIPS

TRIPS = "trips-table"
CLAIMS = "claims-table"
ICE123 = next(t for t in SEED_TRIPS if t.train_number == "ICE123")


@pytest.fixture(autouse=True)
def configured(monkeypatch, dynamodb_client):
    monkeypatch.setenv(ENV_TRIPS_TABLE, TRIPS)
    monkeypatch.setenv(ENV_CLAIMS_TABLE, CLAIMS)
    handlers.use_client(dynamodb_client)
    yield
    handlers.use_client(None)


def json_round_trip(value: Any) -> Any:
    return json.loads(json.dumps(value))


# --- calculate_compensation ---------------------------------------------------------------------


def test_compensation_handler_returns_json_result():
    result = handlers.calculate_compensation({"ticket_price_eur": 100, "delay_minutes": 60}, None)
    assert json_round_trip(result) == result
    assert result["eligible"] is True
    assert result["compensation_eur"] == "25.00"
    assert result["payout_eur"] == "25.00"
    assert result["reason"] == "ELIGIBLE"
    assert {"document": "eu-2021-782", "label": "Art. 19(1)(a)"} in result["references"]
    assert result["confirmation_token"]


def test_compensation_handler_accepts_strings_and_enums():
    result = handlers.calculate_compensation(
        {
            "ticket_price_eur": "29.90",
            "delay_minutes": "60",
            "ticket_kind": "single",
            "travel_class": "2",
            "cause": "own_staff_strike",
            "informed_before_purchase": False,
        },
        None,
    )
    assert result["compensation_eur"] == "7.48"


def test_compensation_handler_reports_invalid_input_as_error():
    result = handlers.calculate_compensation({"ticket_price_eur": 100, "delay_minutes": -1}, None)
    assert result["error"]["code"] == "INVALID_INPUT"
    assert "delay_minutes" in result["error"]["message"]


def test_compensation_handler_reports_missing_field():
    result = handlers.calculate_compensation({"delay_minutes": 60}, None)
    assert result["error"]["code"] == "INVALID_INPUT"
    assert "ticket_price_eur" in result["error"]["message"]


# --- get_train_delay ----------------------------------------------------------------------------


def test_delay_handler_returns_record(dynamodb_stub):
    dynamodb_stub.add_response(
        "get_item",
        {"Item": trip_to_item(ICE123)},
        {"TableName": TRIPS, "Key": {"pk": {"S": "ICE123"}, "sk": {"S": "2026-11-20"}}},
    )
    result = handlers.get_train_delay(
        {"train_number": "ice 123", "travel_date": "2026-11-20"}, None
    )
    assert json_round_trip(result) == result
    assert result["train_number"] == "ICE123"
    assert result["delay_minutes"] == 120
    assert result["status"] == "delayed"
    assert result["cause"] == "operational"
    assert result["scheduled_arrival"].startswith("2026-11-20T")


def test_delay_handler_unknown_trip(dynamodb_stub):
    dynamodb_stub.add_response(
        "get_item",
        {},
        {"TableName": TRIPS, "Key": {"pk": {"S": "ICE999"}, "sk": {"S": "2026-11-20"}}},
    )
    result = handlers.get_train_delay(
        {"train_number": "ICE 999", "travel_date": "2026-11-20"}, None
    )
    assert result["error"]["code"] == "TRIP_NOT_FOUND"
    assert "ICE999" in result["error"]["message"]
    assert "2026-11-20" in result["error"]["message"]


def test_delay_handler_invalid_date_makes_no_call(dynamodb_stub):
    result = handlers.get_train_delay(
        {"train_number": "ICE 123", "travel_date": "2026-13-40"}, None
    )
    assert result["error"]["code"] == "INVALID_INPUT"
    assert "travel_date" in result["error"]["message"]


def test_delay_handler_passes_service_error_code_through(dynamodb_stub):
    dynamodb_stub.add_client_error(
        "get_item", "ProvisionedThroughputExceededException", "slow down"
    )
    result = handlers.get_train_delay(
        {"train_number": "ICE 123", "travel_date": "2026-11-20"}, None
    )
    assert result["error"]["code"] == "ProvisionedThroughputExceededException"


# --- submit_claim -------------------------------------------------------------------------------


def test_submit_handler_stores_and_returns_receipt(dynamodb_stub):
    comp = CompensationRequest(ticket_price_eur=Decimal("100"), delay_minutes=120)
    token = calculate_compensation(comp).confirmation_token
    event = {
        "train_number": "ICE 123",
        "travel_date": "2026-11-20",
        "ticket_price_eur": 100,
        "delay_minutes": 120,
        "passenger_name": "Anna Beispiel",
        "email": "anna@example.com",
        "confirmation_token": token,
    }
    dynamodb_stub.add_response("put_item", {})
    result = handlers.submit_claim(event, None)
    assert json_round_trip(result) == result
    assert result["claim_id"] == f"CLM-{token}"
    assert result["payout_eur"] == "50.00"
    assert result["already_submitted"] is False
    assert result["submitted_at"].endswith("+00:00")


def test_submit_handler_rejects_wrong_token_without_a_call(dynamodb_stub):
    event = {
        "train_number": "ICE 123",
        "travel_date": "2026-11-20",
        "ticket_price_eur": 100,
        "delay_minutes": 120,
        "passenger_name": "Anna Beispiel",
        "email": "anna@example.com",
        "confirmation_token": "0000000000000000",
    }
    result = handlers.submit_claim(event, None)
    assert result["error"]["code"] == "CONFIRMATION_MISMATCH"
