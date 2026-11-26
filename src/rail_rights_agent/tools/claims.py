"""Idempotent claim submission bound to a prior compensation result (design D4)."""

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError

from rail_rights_agent.tools.compensation import (
    Compensation,
    CompensationRequest,
    calculate_compensation,
    round_cents,
)
from rail_rights_agent.tools.delays import normalise_train_number
from rail_rights_agent.tools.errors import ClaimRejected, ToolError, ValidationError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

CLAIM_ID_PREFIX = "CLM-"
NOT_EXISTS = "attribute_not_exists(claim_id)"
STATUS_SUBMITTED = "submitted"


@dataclass(frozen=True)
class ClaimRequest:
    train_number: str
    travel_date: date
    compensation: CompensationRequest
    passenger_name: str
    email: str
    iban: str | None
    confirmation_token: str


@dataclass(frozen=True)
class ClaimReceipt:
    claim_id: str
    payout_eur: Decimal
    already_submitted: bool
    submitted_at: datetime


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _validate(request: ClaimRequest) -> None:
    if not request.confirmation_token.strip():
        raise ValidationError("confirmation_token is required: compute the compensation first")
    if not request.passenger_name.strip():
        raise ValidationError("passenger_name must not be empty")
    if "@" not in request.email:
        raise ValidationError(f"email must contain '@', got {request.email!r}")
    normalise_train_number(request.train_number)


def claim_id_for(request: ClaimRequest, token: str) -> str:
    """The claim id: the token plus who travelled where, so equal amounts never collide (D4)."""
    identity = "|".join(
        [
            token,
            normalise_train_number(request.train_number),
            request.travel_date.isoformat(),
            request.email.strip().lower(),
        ]
    )
    return CLAIM_ID_PREFIX + hashlib.sha256(identity.encode()).hexdigest()[:16].upper()


def claim_item(request: ClaimRequest, result: Compensation, now: datetime) -> dict[str, Any]:
    """The stored record: every field the claim-submission spec lists."""
    comp = request.compensation
    token = result.confirmation_token or request.confirmation_token
    item: dict[str, Any] = {
        "claim_id": {"S": claim_id_for(request, token)},
        "confirmation_token": {"S": token},
        "train_number": {"S": normalise_train_number(request.train_number)},
        "travel_date": {"S": request.travel_date.isoformat()},
        "ticket_kind": {"S": comp.ticket_kind.value},
        "travel_class": {"N": str(comp.travel_class)},
        "ticket_price_eur": {"N": str(round_cents(comp.ticket_price_eur))},
        "delay_minutes": {"N": str(comp.delay_minutes)},
        "cause": {"S": comp.cause.value},
        "informed_before_purchase": {"BOOL": comp.informed_before_purchase},
        "reimbursed_under_art_18": {"BOOL": comp.reimbursed_under_art_18},
        "compensation_eur": {"N": str(result.compensation_eur)},
        "payout_eur": {"N": str(result.payout_eur)},
        "passenger_name": {"S": request.passenger_name},
        "email": {"S": request.email},
        "status": {"S": STATUS_SUBMITTED},
        "submitted_at": {"S": now.isoformat()},
    }
    if request.iban:
        item["iban"] = {"S": request.iban}
    return item


def _receipt(item: Mapping[str, Any], *, already_submitted: bool) -> ClaimReceipt:
    return ClaimReceipt(
        claim_id=item["claim_id"]["S"],
        payout_eur=Decimal(item["payout_eur"]["N"]),
        already_submitted=already_submitted,
        submitted_at=datetime.fromisoformat(item["submitted_at"]["S"]),
    )


class ClaimStore:
    def __init__(self, client: "DynamoDBClient", table_name: str) -> None:
        self._client = client
        self._table = table_name

    def put_new(self, item: Mapping[str, Any]) -> bool:
        """Store the claim unless its id exists; returns whether it was written."""
        try:
            self._client.put_item(TableName=self._table, Item=item, ConditionExpression=NOT_EXISTS)
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def get(self, claim_id: str) -> Mapping[str, Any] | None:
        # Strongly consistent: this read follows a failed conditional write of the same key.
        response = self._client.get_item(
            TableName=self._table, Key={"claim_id": {"S": claim_id}}, ConsistentRead=True
        )
        return response.get("Item")


def submit_claim(
    store: ClaimStore, request: ClaimRequest, *, now: Callable[[], datetime] = utc_now
) -> ClaimReceipt:
    """Validate, recompute, check the token, then write once."""
    _validate(request)
    result = calculate_compensation(request.compensation)
    if result.payout_eur <= 0 or result.confirmation_token is None:
        raise ClaimRejected(
            f"nothing to claim: {result.reason.value.lower().replace('_', ' ')}",
            code=result.reason.value,
        )
    if request.confirmation_token != result.confirmation_token:
        raise ClaimRejected(
            "the confirmation token does not match this claim; recompute the compensation and "
            "confirm again",
            code="CONFIRMATION_MISMATCH",
        )
    item = claim_item(request, result, now())
    if store.put_new(item):
        return _receipt(item, already_submitted=False)
    existing = store.get(item["claim_id"]["S"])
    if existing is None:
        raise ToolError(
            f"claim {item['claim_id']['S']} exists but could not be read", code="CLAIM_CONFLICT"
        )
    return _receipt(existing, already_submitted=True)
