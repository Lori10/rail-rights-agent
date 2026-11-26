"""Spec: train-delay-lookup / the seed data covers every compensation rule."""

from rail_rights_agent.tools.compensation import DelayCause
from rail_rights_agent.tools.delays import TripStatus
from rail_rights_agent.tools.seed_data import SEED_TRIPS


def test_seed_covers_every_delay_band():
    delays = {t.delay_minutes for t in SEED_TRIPS}
    assert {45, 60, 119, 120} <= delays
    assert any(d > 180 for d in delays)


def test_seed_covers_statuses():
    statuses = {t.status for t in SEED_TRIPS}
    assert statuses == {TripStatus.ON_TIME, TripStatus.DELAYED, TripStatus.CANCELLED}


def test_seed_covers_every_cause_category():
    causes = {t.cause for t in SEED_TRIPS}
    assert {
        DelayCause.OPERATIONAL,
        DelayCause.OWN_STAFF_STRIKE,
        DelayCause.INFRASTRUCTURE,
        DelayCause.EXTREME_WEATHER,
        DelayCause.THIRD_PARTY,
    } <= causes


def test_seed_keys_are_unique_and_normalised():
    keys = [(t.train_number, t.travel_date) for t in SEED_TRIPS]
    assert len(keys) == len(set(keys))
    assert all(t.train_number == t.train_number.upper().replace(" ", "") for t in SEED_TRIPS)


def test_on_time_trip_has_zero_delay_and_cancelled_has_no_arrival():
    for trip in SEED_TRIPS:
        if trip.status is TripStatus.ON_TIME:
            assert trip.delay_minutes == 0
        if trip.status is TripStatus.CANCELLED:
            assert trip.actual_arrival is None
        else:
            assert trip.actual_arrival is not None
            minutes = (trip.actual_arrival - trip.scheduled_arrival).total_seconds() / 60
            assert minutes == trip.delay_minutes


def test_reference_trip_ice_123_is_120_minutes_late():
    (trip,) = [t for t in SEED_TRIPS if t.train_number == "ICE123"]
    assert trip.travel_date.isoformat() == "2026-11-20"
    assert trip.delay_minutes == 120
    assert trip.cause is DelayCause.OPERATIONAL
