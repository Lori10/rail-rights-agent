"""Spec: compensation-calculation."""

from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rail_rights_agent.tools.compensation import (
    DB,
    EU,
    Compensation,
    CompensationRequest,
    DelayCause,
    LegalReference,
    ReasonCode,
    TicketKind,
    calculate_compensation,
)
from rail_rights_agent.tools.errors import ValidationError


def calc(price: str, delay: int, **overrides: object) -> Compensation:
    request = CompensationRequest(
        ticket_price_eur=Decimal(price),
        delay_minutes=delay,
        **overrides,  # type: ignore[arg-type]
    )
    return calculate_compensation(request)


def labels(result: Compensation) -> set[tuple[str, str]]:
    return {(r.document, r.label) for r in result.references}


# --- Art. 19(1) percentage bands ----------------------------------------------------------------


def test_45_minutes_not_eligible():
    result = calc("100", 45)
    assert not result.eligible
    assert result.percentage == 0
    assert result.reason is ReasonCode.BELOW_60_MINUTES
    assert result.payout_eur == Decimal("0.00")


@pytest.mark.parametrize(
    ("delay", "percentage", "amount"),
    [(60, 25, "25.00"), (119, 25, "25.00"), (120, 50, "50.00"), (600, 50, "50.00")],
)
def test_percentage_bands(delay: int, percentage: int, amount: str):
    result = calc("100", delay)
    assert result.eligible
    assert result.percentage == percentage
    assert result.compensation_eur == Decimal(amount)
    assert result.payout_eur == Decimal(amount)
    assert result.reason is ReasonCode.ELIGIBLE


# --- Art. 19(3) return tickets ------------------------------------------------------------------


def test_return_ticket_counts_at_half_price():
    result = calc("100", 130, ticket_kind=TicketKind.RETURN)
    assert result.base_price_eur == Decimal("50.00")
    assert result.compensation_eur == Decimal("25.00")
    assert (EU, "Art. 19(3)") in labels(result)


# --- Rounding and minimum payout ----------------------------------------------------------------


def test_rounds_half_up_to_cents():
    assert calc("29.90", 60).compensation_eur == Decimal("7.48")


def test_below_minimum_payout_pays_nothing_and_has_no_token():
    result = calc("12.00", 75)
    assert result.eligible
    assert result.compensation_eur == Decimal("3.00")
    assert result.payout_eur == Decimal("0.00")
    assert result.reason is ReasonCode.BELOW_MINIMUM_PAYOUT
    assert result.confirmation_token is None
    assert (DB, "A.9.2.1") in labels(result)
    assert (EU, "Art. 19(8)") in labels(result)


def test_exactly_minimum_payout_is_paid_with_token():
    result = calc("16.00", 60)
    assert result.compensation_eur == Decimal("4.00")
    assert result.payout_eur == Decimal("4.00")
    assert result.confirmation_token


# --- Exclusions ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "reason", "label"),
    [
        (
            {"cause": DelayCause.EXTREME_WEATHER},
            ReasonCode.EXCLUDED_EXTRAORDINARY,
            "Art. 19(10)(a)",
        ),
        (
            {"cause": DelayCause.PASSENGER_FAULT},
            ReasonCode.EXCLUDED_PASSENGER_FAULT,
            "Art. 19(10)(b)",
        ),
        ({"cause": DelayCause.THIRD_PARTY}, ReasonCode.EXCLUDED_THIRD_PARTY, "Art. 19(10)(c)"),
        ({"informed_before_purchase": True}, ReasonCode.INFORMED_BEFORE_PURCHASE, "Art. 19(9)"),
        ({"reimbursed_under_art_18": True}, ReasonCode.REIMBURSED_UNDER_ART_18, "Art. 19(1)"),
    ],
)
def test_exclusions(overrides: dict[str, object], reason: ReasonCode, label: str):
    result = calc("100", 150, **overrides)
    assert not result.eligible
    assert result.reason is reason
    assert result.payout_eur == Decimal("0.00")
    assert result.confirmation_token is None
    assert (EU, label) in labels(result)


@pytest.mark.parametrize(
    ("cause", "delay", "amount"),
    [
        (DelayCause.OWN_STAFF_STRIKE, 120, "50.00"),
        (DelayCause.INFRASTRUCTURE, 120, "50.00"),
        (DelayCause.OPERATIONAL, 60, "25.00"),
        (DelayCause.UNKNOWN, 60, "25.00"),
    ],
)
def test_strikes_infrastructure_and_unknown_causes_are_compensable(
    cause: DelayCause, delay: int, amount: str
):
    result = calc("100", delay, cause=cause)
    assert result.eligible
    assert result.compensation_eur == Decimal(amount)


# --- Flat rates ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "travel_class", "price", "amount", "label"),
    [
        (TicketKind.SEASON_LONG_DISTANCE, 2, "400", "5.00", "B.13.1"),
        (TicketKind.SEASON_LONG_DISTANCE, 1, "400", "7.50", "B.13.1"),
        (TicketKind.BAHNCARD_100, 2, "7000", "10.00", "C.3.10.1"),
        (TicketKind.BAHNCARD_100, 1, "7000", "15.00", "C.3.10.1"),
    ],
)
def test_flat_rates(kind: TicketKind, travel_class: int, price: str, amount: str, label: str):
    result = calc(
        price,
        70 if kind is TicketKind.SEASON_LONG_DISTANCE else 200,
        ticket_kind=kind,
        travel_class=travel_class,
    )
    assert result.eligible
    assert result.compensation_eur == Decimal(amount)
    assert result.payout_eur == Decimal(amount)
    assert (DB, label) in labels(result)
    assert any("25 %" in note for note in result.notes)


def test_season_ticket_below_60_minutes_not_eligible():
    result = calc("400", 59, ticket_kind=TicketKind.SEASON_LONG_DISTANCE)
    assert not result.eligible
    assert result.reason is ReasonCode.BELOW_60_MINUTES


def test_flat_rate_capped_at_25_percent_of_price():
    result = calc("16", 70, ticket_kind=TicketKind.SEASON_LONG_DISTANCE, travel_class=2)
    assert result.compensation_eur == Decimal("4.00")
    assert result.payout_eur == Decimal("4.00")


# --- Not computable -----------------------------------------------------------------------------


@pytest.mark.parametrize("kind", [TicketKind.DEUTSCHLAND_TICKET, TicketKind.SEASON_REGIONAL])
def test_deutschland_ticket_and_regional_season_not_computable(kind: TicketKind):
    result = calc("58", 90, ticket_kind=kind)
    assert not result.computable
    assert not result.eligible
    assert result.reason is ReasonCode.NOT_COMPUTABLE_FROM_SOURCES
    assert result.payout_eur == Decimal("0.00")
    assert result.confirmation_token is None
    assert (DB, "C.3.10.3") in labels(result)


# --- References ---------------------------------------------------------------------------------


def test_eligible_result_references_art_19_1_and_db_9_2_1():
    result = calc("100", 60)
    assert LegalReference(EU, "Art. 19(1)(a)") in result.references
    assert LegalReference(DB, "A.9.2.1") in result.references
    assert {r.document for r in result.references} <= {EU, DB}


def test_120_minutes_references_art_19_1_b():
    assert (EU, "Art. 19(1)(b)") in labels(calc("100", 120))


# --- Confirmation token -------------------------------------------------------------------------


def test_same_inputs_same_token():
    assert calc("100", 60).confirmation_token == calc("100", 60).confirmation_token


def test_different_price_different_token():
    assert calc("100", 60).confirmation_token != calc("101", 60).confirmation_token


def test_token_is_short_hex():
    token = calc("100", 60).confirmation_token
    assert token is not None
    assert len(token) == 16
    int(token, 16)


# --- Validation ---------------------------------------------------------------------------------


def test_negative_delay_rejected():
    with pytest.raises(ValidationError, match="delay_minutes"):
        calc("100", -5)


@pytest.mark.parametrize("price", ["0", "-1"])
def test_non_positive_price_rejected(price: str):
    with pytest.raises(ValidationError, match="ticket_price_eur"):
        calc(price, 60)


def test_invalid_travel_class_rejected():
    with pytest.raises(ValidationError, match="travel_class"):
        calc("100", 60, travel_class=3)


# --- Properties ---------------------------------------------------------------------------------

prices = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("5000"), places=2)
delays = st.integers(min_value=0, max_value=3000)


@settings(max_examples=300)
@given(price=prices, delay=delays)
def test_never_exceeds_half_the_price(price: Decimal, delay: int):
    result = calc(str(price), delay)
    # DB A.9.2.1 rounds half-up, so half a cent above 50 % is allowed (spec property).
    assert result.compensation_eur <= (price / 2).quantize(Decimal("0.01"), ROUND_HALF_UP)
    assert result.payout_eur <= result.compensation_eur


@settings(max_examples=300)
@given(price=prices, delay=delays, extra=st.integers(min_value=0, max_value=3000))
def test_monotonic_in_delay(price: Decimal, delay: int, extra: int):
    assert (
        calc(str(price), delay + extra).compensation_eur >= calc(str(price), delay).compensation_eur
    )


@settings(max_examples=300)
@given(price=prices, delay=delays)
def test_payout_is_zero_or_at_least_four_euros(price: Decimal, delay: int):
    payout = calc(str(price), delay).payout_eur
    assert payout == Decimal("0.00") or payout >= Decimal("4.00")
    assert payout == payout.quantize(Decimal("0.01"))


@settings(max_examples=100)
@given(price=prices, delay=st.integers(min_value=60, max_value=3000))
def test_token_present_iff_payout(price: Decimal, delay: int):
    result = calc(str(price), delay)
    assert (result.confirmation_token is not None) == (result.payout_eur > 0)
    if result.confirmation_token is not None:
        assert calc(str(price), delay).confirmation_token == result.confirmation_token
