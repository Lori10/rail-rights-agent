"""Lambda handlers: one per tool, tool arguments as the event, JSON out, errors as data (D5).

The event is exactly what an AgentCore Gateway Lambda target receives: a map of the tool's
input-schema properties. ``context`` is accepted and ignored. Nothing is raised: every rejection
comes back as ``{"error": {"code": ..., "message": ...}}`` so the model can explain it.
"""

import os
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from rail_rights_agent.tools import compensation as rules
from rail_rights_agent.tools.claims import ClaimReceipt, ClaimRequest, ClaimStore
from rail_rights_agent.tools.claims import submit_claim as store_claim
from rail_rights_agent.tools.delays import TripRecord, TripStore, parse_travel_date
from rail_rights_agent.tools.deployment import ENV_CLAIMS_TABLE, ENV_TRIPS_TABLE
from rail_rights_agent.tools.errors import ToolError, ValidationError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

Event = Mapping[str, Any]
Result = dict[str, Any]
_CLIENT: "DynamoDBClient | None" = None


def use_client(client: "DynamoDBClient | None") -> None:
    """Inject the DynamoDB client (tests, in-process agent); ``None`` returns to the default."""
    global _CLIENT
    _CLIENT = client


def _client() -> "DynamoDBClient":
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = boto3.client("dynamodb")
    return _CLIENT


def _table(env_var: str) -> str:
    name = os.environ.get(env_var, "").strip()
    if not name:
        raise ToolError(f"{env_var} is not set on this function", code="MISCONFIGURED")
    return name


# --- Event parsing ------------------------------------------------------------------------------


def _required(event: Event, field: str) -> Any:
    if field not in event or event[field] is None or event[field] == "":
        raise ValidationError(f"{field} is required")
    return event[field]


def _str(event: Event, field: str) -> str:
    return str(_required(event, field)).strip()


def _optional_str(event: Event, field: str) -> str | None:
    value = event.get(field)
    return str(value).strip() or None if value is not None else None


def _decimal(event: Event, field: str) -> Decimal:
    raw = _required(event, field)
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        raise ValidationError(f"{field} must be a number, got {raw!r}") from None


def _int(event: Event, field: str, default: int | None = None) -> int:
    raw = event.get(field, default)
    if raw is None:
        raise ValidationError(f"{field} is required")
    try:
        return int(str(raw))
    except ValueError:
        raise ValidationError(f"{field} must be a whole number, got {raw!r}") from None


def _bool(event: Event, field: str) -> bool:
    raw = event.get(field, False)
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no", ""):
        return False
    raise ValidationError(f"{field} must be true or false, got {raw!r}")


def _enum[E: StrEnum](event: Event, field: str, kind: type[E], default: E) -> E:
    raw = event.get(field)
    if raw is None or raw == "":
        return default
    try:
        return kind(str(raw).strip().lower())
    except ValueError:
        allowed = ", ".join(m.value for m in kind)
        raise ValidationError(f"{field} must be one of {allowed}, got {raw!r}") from None


def compensation_request(event: Event) -> rules.CompensationRequest:
    return rules.CompensationRequest(
        ticket_price_eur=_decimal(event, "ticket_price_eur"),
        delay_minutes=_int(event, "delay_minutes"),
        ticket_kind=_enum(event, "ticket_kind", rules.TicketKind, rules.TicketKind.SINGLE),
        travel_class=_int(event, "travel_class", 2),
        cause=_enum(event, "cause", rules.DelayCause, rules.DelayCause.UNKNOWN),
        informed_before_purchase=_bool(event, "informed_before_purchase"),
        reimbursed_under_art_18=_bool(event, "reimbursed_under_art_18"),
    )


def claim_request(event: Event) -> ClaimRequest:
    return ClaimRequest(
        train_number=_str(event, "train_number"),
        travel_date=parse_travel_date(_str(event, "travel_date")),
        compensation=compensation_request(event),
        passenger_name=_str(event, "passenger_name"),
        email=_str(event, "email"),
        iban=_optional_str(event, "iban"),
        confirmation_token=str(event.get("confirmation_token") or "").strip(),
    )


# --- Result serialisation -----------------------------------------------------------------------


def compensation_json(result: rules.Compensation) -> Result:
    return {
        "eligible": result.eligible,
        "computable": result.computable,
        "percentage": result.percentage,
        "base_price_eur": str(result.base_price_eur),
        "compensation_eur": str(result.compensation_eur),
        "payout_eur": str(result.payout_eur),
        "reason": result.reason.value,
        "references": [{"document": r.document, "label": r.label} for r in result.references],
        "notes": list(result.notes),
        "confirmation_token": result.confirmation_token,
    }


def trip_json(trip: TripRecord) -> Result:
    return {
        "train_number": trip.train_number,
        "travel_date": trip.travel_date.isoformat(),
        "origin": trip.origin,
        "destination": trip.destination,
        "scheduled_departure": trip.scheduled_departure.isoformat(),
        "scheduled_arrival": trip.scheduled_arrival.isoformat(),
        "actual_arrival": trip.actual_arrival.isoformat() if trip.actual_arrival else None,
        "delay_minutes": trip.delay_minutes,
        "status": trip.status.value,
        "cause": trip.cause.value,
    }


def receipt_json(receipt: ClaimReceipt) -> Result:
    return {
        "claim_id": receipt.claim_id,
        "payout_eur": str(receipt.payout_eur),
        "already_submitted": receipt.already_submitted,
        "submitted_at": receipt.submitted_at.isoformat(),
    }


def _error(code: str, message: str) -> Result:
    return {"error": {"code": code, "message": message}}


def _guarded(run: Callable[[], Result]) -> Result:
    try:
        return run()
    except ToolError as err:
        return _error(err.code, err.message)
    except ClientError as err:
        error = err.response.get("Error", {})
        return _error(error.get("Code", "ServiceError"), error.get("Message", str(err)))


# --- Handlers -----------------------------------------------------------------------------------


def get_train_delay(event: Event, context: object) -> Result:
    def run() -> Result:
        train = _str(event, "train_number")
        day = parse_travel_date(_str(event, "travel_date"))
        store = TripStore(_client(), _table(ENV_TRIPS_TABLE))
        return trip_json(store.get(train, day))

    return _guarded(run)


def calculate_compensation(event: Event, context: object) -> Result:
    return _guarded(
        lambda: compensation_json(rules.calculate_compensation(compensation_request(event)))
    )


def submit_claim(event: Event, context: object) -> Result:
    def run() -> Result:
        request = claim_request(event)
        store = ClaimStore(_client(), _table(ENV_CLAIMS_TABLE))
        return receipt_json(store_claim(store, request))

    return _guarded(run)
