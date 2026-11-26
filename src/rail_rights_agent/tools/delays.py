"""Train delay lookup over the mock trips table (design D3)."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from rail_rights_agent.tools.compensation import DelayCause
from rail_rights_agent.tools.errors import TripNotFound, ValidationError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

PARTITION_KEY = "pk"  # normalised train number
SORT_KEY = "sk"  # travel date, ISO


class TripStatus(StrEnum):
    ON_TIME = "on_time"
    DELAYED = "delayed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TripRecord:
    train_number: str
    travel_date: date
    origin: str
    destination: str
    scheduled_departure: datetime
    scheduled_arrival: datetime
    actual_arrival: datetime | None
    delay_minutes: int
    status: TripStatus
    cause: DelayCause


def normalise_train_number(raw: str) -> str:
    """``"ice 123"`` → ``"ICE123"``: upper case, no whitespace."""
    train = re.sub(r"\s+", "", raw).upper()
    if not train:
        raise ValidationError("train_number must not be empty")
    return train


def parse_travel_date(raw: str) -> date:
    """A calendar date in ``YYYY-MM-DD`` form; anything else is rejected before any AWS call."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw or ""):
        raise ValidationError(f"travel_date must be a date in YYYY-MM-DD form, got {raw!r}")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValidationError(f"travel_date is not a valid calendar date: {raw!r}") from None


def trip_key(train_number: str, travel_date: date) -> dict[str, Any]:
    return {PARTITION_KEY: {"S": train_number}, SORT_KEY: {"S": travel_date.isoformat()}}


def trip_to_item(trip: TripRecord) -> dict[str, Any]:
    item = {
        **trip_key(trip.train_number, trip.travel_date),
        "origin": {"S": trip.origin},
        "destination": {"S": trip.destination},
        "scheduled_departure": {"S": trip.scheduled_departure.isoformat()},
        "scheduled_arrival": {"S": trip.scheduled_arrival.isoformat()},
        "delay_minutes": {"N": str(trip.delay_minutes)},
        "status": {"S": trip.status.value},
        "cause": {"S": trip.cause.value},
    }
    if trip.actual_arrival is not None:
        item["actual_arrival"] = {"S": trip.actual_arrival.isoformat()}
    return item


def item_to_trip(item: Mapping[str, Any]) -> TripRecord:
    actual = item.get("actual_arrival")
    return TripRecord(
        train_number=item[PARTITION_KEY]["S"],
        travel_date=date.fromisoformat(item[SORT_KEY]["S"]),
        origin=item["origin"]["S"],
        destination=item["destination"]["S"],
        scheduled_departure=datetime.fromisoformat(item["scheduled_departure"]["S"]),
        scheduled_arrival=datetime.fromisoformat(item["scheduled_arrival"]["S"]),
        actual_arrival=datetime.fromisoformat(actual["S"]) if actual else None,
        delay_minutes=int(item["delay_minutes"]["N"]),
        status=TripStatus(item["status"]["S"]),
        cause=DelayCause(item["cause"]["S"]),
    )


class TripStore:
    def __init__(self, client: "DynamoDBClient", table_name: str) -> None:
        self._client = client
        self._table = table_name

    def get(self, train_number: str, travel_date: date) -> TripRecord:
        train = normalise_train_number(train_number)
        response = self._client.get_item(TableName=self._table, Key=trip_key(train, travel_date))
        item = response.get("Item")
        if not item:
            raise TripNotFound(f"no trip record for {train} on {travel_date.isoformat()}")
        return item_to_trip(item)

    def put_many(self, trips: Iterable[TripRecord]) -> int:
        """Write each trip under its key; re-running overwrites rather than duplicates."""
        count = 0
        for trip in trips:
            self._client.put_item(TableName=self._table, Item=trip_to_item(trip))
            count += 1
        return count
