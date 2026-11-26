"""Fixed mock trips covering every compensation rule (design D3). Dates are fixed on purpose."""

from datetime import date, datetime, timedelta, timezone

from rail_rights_agent.tools.compensation import DelayCause
from rail_rights_agent.tools.delays import TripRecord, TripStatus

CET = timezone(timedelta(hours=1))


def _trip(
    train: str,
    day: str,
    origin: str,
    destination: str,
    departure: str,
    arrival: str,
    delay: int,
    status: TripStatus,
    cause: DelayCause,
) -> TripRecord:
    travel_date = date.fromisoformat(day)
    dep_h, dep_m = (int(x) for x in departure.split(":"))
    arr_h, arr_m = (int(x) for x in arrival.split(":"))
    scheduled_departure = datetime.combine(travel_date, datetime.min.time(), CET).replace(
        hour=dep_h, minute=dep_m
    )
    scheduled_arrival = datetime.combine(travel_date, datetime.min.time(), CET).replace(
        hour=arr_h, minute=arr_m
    )
    actual = (
        None if status is TripStatus.CANCELLED else scheduled_arrival + timedelta(minutes=delay)
    )
    return TripRecord(
        train_number=train,
        travel_date=travel_date,
        origin=origin,
        destination=destination,
        scheduled_departure=scheduled_departure,
        scheduled_arrival=scheduled_arrival,
        actual_arrival=actual,
        delay_minutes=delay,
        status=status,
        cause=cause,
    )


D, C, ON = TripStatus.DELAYED, TripStatus.CANCELLED, TripStatus.ON_TIME

SEED_TRIPS: tuple[TripRecord, ...] = (
    # The reference case: 120 minutes, 50 %.
    _trip(
        "ICE123",
        "2026-11-20",
        "Berlin Hbf",
        "München Hbf",
        "08:00",
        "12:00",
        120,
        D,
        DelayCause.OPERATIONAL,
    ),
    _trip(
        "ICE587",
        "2026-11-20",
        "Hamburg Hbf",
        "Frankfurt(Main) Hbf",
        "07:30",
        "11:10",
        0,
        ON,
        DelayCause.OPERATIONAL,
    ),
    # Cancelled: the delay is the one incurred reaching the destination with the next service.
    _trip(
        "IC2045",
        "2026-11-20",
        "Hamburg Hbf",
        "Köln Hbf",
        "09:00",
        "13:00",
        140,
        C,
        DelayCause.INFRASTRUCTURE,
    ),
    _trip(
        "ICE703",
        "2026-11-21",
        "Köln Hbf",
        "Berlin Hbf",
        "06:48",
        "11:12",
        45,
        D,
        DelayCause.OPERATIONAL,
    ),
    _trip(
        "RE4",
        "2026-11-21",
        "Aachen Hbf",
        "Dortmund Hbf",
        "10:05",
        "12:30",
        60,
        D,
        DelayCause.INFRASTRUCTURE,
    ),
    _trip(
        "ICE1001",
        "2026-11-21",
        "München Hbf",
        "Hamburg Hbf",
        "09:17",
        "15:00",
        119,
        D,
        DelayCause.OWN_STAFF_STRIKE,
    ),
    _trip(
        "IC2311",
        "2026-11-22",
        "Stuttgart Hbf",
        "Hamburg Hbf",
        "08:00",
        "13:30",
        200,
        D,
        DelayCause.EXTREME_WEATHER,
    ),
    _trip(
        "ICE1622",
        "2026-11-22",
        "München Hbf",
        "Dortmund Hbf",
        "10:00",
        "16:00",
        95,
        D,
        DelayCause.THIRD_PARTY,
    ),
    _trip(
        "ICE517",
        "2026-11-23",
        "Berlin Hbf",
        "Frankfurt(Main) Hbf",
        "11:00",
        "15:00",
        185,
        D,
        DelayCause.OPERATIONAL,
    ),
    _trip(
        "RE1",
        "2026-11-23",
        "Berlin Hbf",
        "Magdeburg Hbf",
        "08:00",
        "09:45",
        30,
        D,
        DelayCause.UNKNOWN,
    ),
    _trip(
        "ICE279",
        "2026-11-24",
        "Berlin Hbf",
        "Hamburg Hbf",
        "12:00",
        "14:00",
        90,
        C,
        DelayCause.OWN_STAFF_STRIKE,
    ),
    _trip(
        "ICE1055",
        "2026-11-25",
        "Frankfurt(Main) Hbf",
        "Berlin Hbf",
        "07:00",
        "11:05",
        61,
        D,
        DelayCause.INFRASTRUCTURE,
    ),
)
