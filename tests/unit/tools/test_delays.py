"""Spec: train-delay-lookup (lookup, normalisation, errors, store)."""

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from botocore.stub import Stubber

from rail_rights_agent.tools.compensation import DelayCause
from rail_rights_agent.tools.delays import (
    TripRecord,
    TripStatus,
    TripStore,
    item_to_trip,
    normalise_train_number,
    parse_travel_date,
    trip_to_item,
)
from rail_rights_agent.tools.errors import TripNotFound, ValidationError

TABLE = "trips-table"
CET = timezone(timedelta(hours=1))
DAY = date(2026, 11, 20)

DELAYED = TripRecord(
    train_number="ICE123",
    travel_date=DAY,
    origin="Berlin Hbf",
    destination="München Hbf",
    scheduled_departure=datetime(2026, 11, 20, 8, 0, tzinfo=CET),
    scheduled_arrival=datetime(2026, 11, 20, 12, 0, tzinfo=CET),
    actual_arrival=datetime(2026, 11, 20, 13, 15, tzinfo=CET),
    delay_minutes=75,
    status=TripStatus.DELAYED,
    cause=DelayCause.OPERATIONAL,
)
CANCELLED = TripRecord(
    train_number="IC2045",
    travel_date=DAY,
    origin="Hamburg Hbf",
    destination="Köln Hbf",
    scheduled_departure=datetime(2026, 11, 20, 9, 0, tzinfo=CET),
    scheduled_arrival=datetime(2026, 11, 20, 13, 0, tzinfo=CET),
    actual_arrival=None,
    delay_minutes=140,
    status=TripStatus.CANCELLED,
    cause=DelayCause.INFRASTRUCTURE,
)


def key(train: str, day: date) -> dict[str, Any]:
    return {"pk": {"S": train}, "sk": {"S": day.isoformat()}}


def expect_get(stub: Stubber, train: str, day: date, record: TripRecord | None) -> None:
    response: dict[str, Any] = {"Item": trip_to_item(record)} if record else {}
    stub.add_response("get_item", response, {"TableName": TABLE, "Key": key(train, day)})


@pytest.fixture
def store(dynamodb_client) -> TripStore:
    return TripStore(dynamodb_client, TABLE)


# --- Item mapping -------------------------------------------------------------------------------


def test_delayed_record_round_trips_through_an_item():
    item = trip_to_item(DELAYED)
    assert item["pk"] == {"S": "ICE123"}
    assert item["sk"] == {"S": "2026-11-20"}
    assert item["delay_minutes"] == {"N": "75"}
    assert item["status"] == {"S": "delayed"}
    assert item["cause"] == {"S": "operational"}
    assert item_to_trip(item) == DELAYED


def test_cancelled_record_has_no_actual_arrival():
    item = trip_to_item(CANCELLED)
    assert "actual_arrival" not in item
    restored = item_to_trip(item)
    assert restored.status is TripStatus.CANCELLED
    assert restored.actual_arrival is None
    assert restored.delay_minutes == 140


# --- Lookup -------------------------------------------------------------------------------------


def test_lookup_returns_delayed_record(store, dynamodb_stub):
    expect_get(dynamodb_stub, "ICE123", DAY, DELAYED)
    assert store.get("ICE 123", DAY) == DELAYED


def test_lookup_returns_cancelled_record(store, dynamodb_stub):
    expect_get(dynamodb_stub, "IC2045", DAY, CANCELLED)
    assert store.get("IC2045", DAY) == CANCELLED


@pytest.mark.parametrize("raw", ["ice 123", "ICE123", "ICE 123", " Ice  123 "])
def test_train_number_normalised(raw: str):
    assert normalise_train_number(raw) == "ICE123"


def test_lookup_with_lower_case_and_space_hits_normalised_key(store, dynamodb_stub):
    expect_get(dynamodb_stub, "ICE123", DAY, DELAYED)
    assert store.get("ice 123", DAY) == DELAYED


def test_unknown_trip_names_train_and_date(store, dynamodb_stub):
    expect_get(dynamodb_stub, "ICE999", DAY, None)
    with pytest.raises(TripNotFound) as err:
        store.get("ICE 999", DAY)
    assert err.value.code == "TRIP_NOT_FOUND"
    assert "ICE999" in err.value.message
    assert "2026-11-20" in err.value.message


def test_empty_train_number_rejected():
    with pytest.raises(ValidationError, match="train_number"):
        normalise_train_number("  ")


# --- Dates --------------------------------------------------------------------------------------


def test_parse_valid_date():
    assert parse_travel_date("2026-11-20") == DAY


@pytest.mark.parametrize("raw", ["2026-13-40", "20.11.2026", "", "2026-11-20T08:00"])
def test_invalid_date_rejected_before_any_call(raw: str):
    with pytest.raises(ValidationError, match="travel_date"):
        parse_travel_date(raw)


# --- Seeding ------------------------------------------------------------------------------------


def test_put_many_writes_each_record_by_key(store, dynamodb_stub):
    for record in (DELAYED, CANCELLED):
        dynamodb_stub.add_response(
            "put_item", {}, {"TableName": TABLE, "Item": trip_to_item(record)}
        )
    assert store.put_many([DELAYED, CANCELLED]) == 2


def test_seeding_twice_uses_the_same_keys(store, dynamodb_stub):
    for _ in range(2):
        dynamodb_stub.add_response(
            "put_item", {}, {"TableName": TABLE, "Item": trip_to_item(DELAYED)}
        )
    store.put_many([DELAYED])
    store.put_many([DELAYED])


def test_timestamps_keep_their_offset():
    restored = item_to_trip(trip_to_item(DELAYED))
    assert restored.scheduled_departure.utcoffset() == timedelta(hours=1)
    assert restored.scheduled_departure.astimezone(UTC).hour == 7
