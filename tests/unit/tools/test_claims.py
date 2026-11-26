"""Spec: claim-submission."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from botocore.stub import Stubber

from rail_rights_agent.tools.claims import (
    ClaimReceipt,
    ClaimRequest,
    ClaimStore,
    claim_item,
    submit_claim,
)
from rail_rights_agent.tools.compensation import (
    CompensationRequest,
    DelayCause,
    TicketKind,
    calculate_compensation,
)
from rail_rights_agent.tools.errors import ClaimRejected, ValidationError

TABLE = "claims-table"
NOW = datetime(2026, 11, 26, 10, 30, tzinfo=UTC)
DAY = date(2026, 11, 20)
CONDITION = "attribute_not_exists(claim_id)"

COMP = CompensationRequest(
    ticket_price_eur=Decimal("100"),
    delay_minutes=120,
    ticket_kind=TicketKind.SINGLE,
    travel_class=2,
    cause=DelayCause.OPERATIONAL,
)
TOKEN = calculate_compensation(COMP).confirmation_token or ""


def request(**overrides: Any) -> ClaimRequest:
    fields: dict[str, Any] = {
        "train_number": "ICE 123",
        "travel_date": DAY,
        "compensation": COMP,
        "passenger_name": "Anna Beispiel",
        "email": "anna@example.com",
        "iban": "DE02120300000000202051",
        "confirmation_token": TOKEN,
    }
    fields.update(overrides)
    return ClaimRequest(**fields)


def now() -> datetime:
    return NOW


@pytest.fixture
def store(dynamodb_client) -> ClaimStore:
    return ClaimStore(dynamodb_client, TABLE)


def expected_item(submitted_at: str = "2026-11-26T10:30:00+00:00") -> dict[str, Any]:
    return {
        "claim_id": {"S": f"CLM-{TOKEN}"},
        "confirmation_token": {"S": TOKEN},
        "train_number": {"S": "ICE123"},
        "travel_date": {"S": "2026-11-20"},
        "ticket_kind": {"S": "single"},
        "travel_class": {"N": "2"},
        "ticket_price_eur": {"N": "100"},
        "delay_minutes": {"N": "120"},
        "cause": {"S": "operational"},
        "informed_before_purchase": {"BOOL": False},
        "reimbursed_under_art_18": {"BOOL": False},
        "compensation_eur": {"N": "50.00"},
        "payout_eur": {"N": "50.00"},
        "passenger_name": {"S": "Anna Beispiel"},
        "email": {"S": "anna@example.com"},
        "iban": {"S": "DE02120300000000202051"},
        "status": {"S": "submitted"},
        "submitted_at": {"S": submitted_at},
    }


def expect_put(stub: Stubber, item: dict[str, Any]) -> None:
    stub.add_response(
        "put_item", {}, {"TableName": TABLE, "Item": item, "ConditionExpression": CONDITION}
    )


# --- Happy path ---------------------------------------------------------------------------------


def test_matching_token_stores_the_full_record(store, dynamodb_stub):
    expect_put(dynamodb_stub, expected_item())
    receipt = submit_claim(store, request(), now=now)
    assert receipt == ClaimReceipt(
        claim_id=f"CLM-{TOKEN}",
        payout_eur=Decimal("50.00"),
        already_submitted=False,
        submitted_at=NOW,
    )


def test_claim_item_matches_the_spec_fields():
    item = claim_item(request(), calculate_compensation(COMP), NOW)
    assert item == expected_item()


def test_iban_is_optional():
    item = claim_item(request(iban=None), calculate_compensation(COMP), NOW)
    assert "iban" not in item


# --- Token checks -------------------------------------------------------------------------------


def test_empty_token_rejected_before_any_call(store, dynamodb_stub):
    with pytest.raises(ValidationError, match="confirmation_token"):
        submit_claim(store, request(confirmation_token=""), now=now)


def test_token_for_other_inputs_rejected(store, dynamodb_stub):
    other = CompensationRequest(ticket_price_eur=Decimal("101"), delay_minutes=120)
    wrong = calculate_compensation(other).confirmation_token
    with pytest.raises(ClaimRejected) as err:
        submit_claim(store, request(confirmation_token=wrong), now=now)
    assert err.value.code == "CONFIRMATION_MISMATCH"


# --- Nothing to claim ---------------------------------------------------------------------------


def test_below_minimum_payout_rejected(store, dynamodb_stub):
    small = CompensationRequest(ticket_price_eur=Decimal("12"), delay_minutes=75)
    with pytest.raises(ClaimRejected) as err:
        submit_claim(store, request(compensation=small, confirmation_token="ANY"), now=now)
    assert err.value.code == "BELOW_MINIMUM_PAYOUT"


def test_not_eligible_rejected_with_its_reason(store, dynamodb_stub):
    short = CompensationRequest(ticket_price_eur=Decimal("100"), delay_minutes=30)
    with pytest.raises(ClaimRejected) as err:
        submit_claim(store, request(compensation=short, confirmation_token="ANY"), now=now)
    assert err.value.code == "BELOW_60_MINUTES"


# --- Idempotency --------------------------------------------------------------------------------


def test_second_submission_returns_existing_claim(store, dynamodb_stub):
    expect_put(dynamodb_stub, expected_item())
    first = submit_claim(store, request(), now=now)

    dynamodb_stub.add_client_error(
        "put_item",
        "ConditionalCheckFailedException",
        "The conditional request failed",
        expected_params={
            "TableName": TABLE,
            "Item": expected_item(submitted_at="2026-11-26T11:30:00+00:00"),
            "ConditionExpression": CONDITION,
        },
    )
    dynamodb_stub.add_response(
        "get_item",
        {"Item": expected_item()},
        {"TableName": TABLE, "Key": {"claim_id": {"S": f"CLM-{TOKEN}"}}},
    )
    second = submit_claim(store, request(), now=lambda: NOW.replace(hour=11))
    assert second.claim_id == first.claim_id
    assert second.already_submitted
    assert second.payout_eur == Decimal("50.00")
    assert second.submitted_at == NOW


# --- Field validation ---------------------------------------------------------------------------


def test_empty_name_rejected(store, dynamodb_stub):
    with pytest.raises(ValidationError, match="passenger_name"):
        submit_claim(store, request(passenger_name="  "), now=now)


def test_email_without_at_rejected(store, dynamodb_stub):
    with pytest.raises(ValidationError, match="email"):
        submit_claim(store, request(email="anna.example.com"), now=now)
