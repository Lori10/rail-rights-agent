"""Deterministic delay compensation: Art. 19 of Regulation (EU) 2021/782 and the DB conditions.

Every number below sits next to the clause it comes from (design D1). The LLM never computes
money; it explains this result and cites the referenced passages. Rules not settled by the two
source documents return ``NOT_COMPUTABLE_FROM_SOURCES`` rather than a guess.
"""

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from rail_rights_agent.tools.errors import ValidationError

# Document ids as the knowledge-base catalogue names them, so a reference can be retrieved.
EU = "eu-2021-782"
DB = "db-befoerderungsbedingungen"

CENT = Decimal("0.01")
# DB A.9.2.1: "Entschädigungsbeträge unter 4 € werden nicht ausgezahlt" (Art. 19(8) allows ≤ €4).
MINIMUM_PAYOUT_EUR = Decimal("4.00")
# Art. 19(1)(a)/(b): the two delay bands.
DELAY_25_PERCENT = 60
DELAY_50_PERCENT = 120
# DB B.13.1 and C.3.10.1: flat rates are capped at 25 % of the ticket price.
FLAT_RATE_CAP_PERCENT = 25


class TicketKind(StrEnum):
    SINGLE = "single"
    RETURN = "return"
    SEASON_LONG_DISTANCE = "season_long_distance"  # ICE / IC-EC Zeitkarte, DB B.13.1
    BAHNCARD_100 = "bahncard_100"  # DB C.3.10.1
    DEUTSCHLAND_TICKET = "deutschland_ticket"  # own tariff, DB C.3.10.3: not in the sources
    SEASON_REGIONAL = "season_regional"  # Verbund tariffs: not in the sources


class DelayCause(StrEnum):
    OPERATIONAL = "operational"
    OWN_STAFF_STRIKE = "own_staff_strike"  # Art. 19(10), last sentence: not exempt
    INFRASTRUCTURE = "infrastructure"  # Art. 19(10), last sentence: not exempt
    EXTREME_WEATHER = "extreme_weather"  # Art. 19(10)(a)
    PASSENGER_FAULT = "passenger_fault"  # Art. 19(10)(b)
    THIRD_PARTY = "third_party"  # Art. 19(10)(c)
    UNKNOWN = "unknown"  # burden of proof lies with the railway: compensable


class ReasonCode(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    BELOW_60_MINUTES = "BELOW_60_MINUTES"
    INFORMED_BEFORE_PURCHASE = "INFORMED_BEFORE_PURCHASE"
    REIMBURSED_UNDER_ART_18 = "REIMBURSED_UNDER_ART_18"
    EXCLUDED_EXTRAORDINARY = "EXCLUDED_EXTRAORDINARY"
    EXCLUDED_PASSENGER_FAULT = "EXCLUDED_PASSENGER_FAULT"
    EXCLUDED_THIRD_PARTY = "EXCLUDED_THIRD_PARTY"
    BELOW_MINIMUM_PAYOUT = "BELOW_MINIMUM_PAYOUT"
    NOT_COMPUTABLE_FROM_SOURCES = "NOT_COMPUTABLE_FROM_SOURCES"


@dataclass(frozen=True)
class LegalReference:
    document: str
    label: str


@dataclass(frozen=True)
class CompensationRequest:
    ticket_price_eur: Decimal
    delay_minutes: int
    ticket_kind: TicketKind = TicketKind.SINGLE
    travel_class: int = 2
    cause: DelayCause = DelayCause.UNKNOWN
    informed_before_purchase: bool = False
    reimbursed_under_art_18: bool = False


@dataclass(frozen=True)
class Compensation:
    eligible: bool
    computable: bool
    percentage: int
    base_price_eur: Decimal
    compensation_eur: Decimal
    payout_eur: Decimal
    reason: ReasonCode
    references: tuple[LegalReference, ...]
    notes: tuple[str, ...]
    confirmation_token: str | None


# --- Rules table --------------------------------------------------------------------------------

ART_19_1 = LegalReference(EU, "Art. 19(1)")
ART_19_1_A = LegalReference(EU, "Art. 19(1)(a)")
ART_19_1_B = LegalReference(EU, "Art. 19(1)(b)")
ART_19_3 = LegalReference(EU, "Art. 19(3)")
ART_19_8 = LegalReference(EU, "Art. 19(8)")
ART_19_9 = LegalReference(EU, "Art. 19(9)")
ART_19_10 = LegalReference(EU, "Art. 19(10)")
DB_9_2_1 = LegalReference(DB, "A.9.2.1")
DB_13_1 = LegalReference(DB, "B.13.1")
DB_3_10_1 = LegalReference(DB, "C.3.10.1")
DB_3_10_3 = LegalReference(DB, "C.3.10.3")

# Art. 19(10)(a) to (c): causes that free the railway from compensation.
EXCLUDED_CAUSES: dict[DelayCause, tuple[ReasonCode, LegalReference]] = {
    DelayCause.EXTREME_WEATHER: (
        ReasonCode.EXCLUDED_EXTRAORDINARY,
        LegalReference(EU, "Art. 19(10)(a)"),
    ),
    DelayCause.PASSENGER_FAULT: (
        ReasonCode.EXCLUDED_PASSENGER_FAULT,
        LegalReference(EU, "Art. 19(10)(b)"),
    ),
    DelayCause.THIRD_PARTY: (ReasonCode.EXCLUDED_THIRD_PARTY, LegalReference(EU, "Art. 19(10)(c)")),
}

# Flat rate per delay case of 60 minutes or more, by (ticket kind, travel class).
FLAT_RATES: dict[tuple[TicketKind, int], tuple[Decimal, LegalReference]] = {
    (TicketKind.SEASON_LONG_DISTANCE, 2): (Decimal("5.00"), DB_13_1),
    (TicketKind.SEASON_LONG_DISTANCE, 1): (Decimal("7.50"), DB_13_1),
    (TicketKind.BAHNCARD_100, 2): (Decimal("10.00"), DB_3_10_1),
    (TicketKind.BAHNCARD_100, 1): (Decimal("15.00"), DB_3_10_1),
}

NOT_COMPUTABLE_KINDS = {TicketKind.DEUTSCHLAND_TICKET, TicketKind.SEASON_REGIONAL}

FLAT_RATE_NOTE = (
    "Flat rate per delay case; in total at most 25 % of the ticket price is paid out over the "
    "ticket's validity period. Earlier payouts are not tracked here."
)
RETURN_NOTE = "Return ticket without a per-leg price: compensation is based on half the price paid."


# --- Calculation --------------------------------------------------------------------------------


def _validate(request: CompensationRequest) -> None:
    if request.ticket_price_eur <= 0:
        raise ValidationError(f"ticket_price_eur must be positive, got {request.ticket_price_eur}")
    if request.delay_minutes < 0:
        raise ValidationError(f"delay_minutes must not be negative, got {request.delay_minutes}")
    if request.travel_class not in (1, 2):
        raise ValidationError(f"travel_class must be 1 or 2, got {request.travel_class}")


def _cents(amount: Decimal) -> Decimal:
    """Round "kaufmännisch" (half up) to cents, as DB A.9.2.1 requires."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _not_eligible(
    request: CompensationRequest,
    reason: ReasonCode,
    references: tuple[LegalReference, ...],
    *,
    computable: bool = True,
) -> Compensation:
    return Compensation(
        eligible=False,
        computable=computable,
        percentage=0,
        base_price_eur=_cents(request.ticket_price_eur),
        compensation_eur=Decimal("0.00"),
        payout_eur=Decimal("0.00"),
        reason=reason,
        references=references,
        notes=(),
        confirmation_token=None,
    )


def confirmation_token(request: CompensationRequest, payout_eur: Decimal) -> str:
    """Digest binding the payout to the inputs that produced it (design D2; not a secret)."""
    canonical = json.dumps(
        {
            "ticket_price_eur": str(_cents(request.ticket_price_eur)),
            "delay_minutes": request.delay_minutes,
            "ticket_kind": request.ticket_kind.value,
            "travel_class": request.travel_class,
            "cause": request.cause.value,
            "payout_eur": str(payout_eur),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16].upper()


def calculate_compensation(request: CompensationRequest) -> Compensation:
    """Apply the rules in order: validity, computability, exclusions, delay band, amount, payout."""
    _validate(request)

    if request.ticket_kind in NOT_COMPUTABLE_KINDS:
        return _not_eligible(
            request, ReasonCode.NOT_COMPUTABLE_FROM_SOURCES, (DB_3_10_3,), computable=False
        )
    if request.informed_before_purchase:
        return _not_eligible(request, ReasonCode.INFORMED_BEFORE_PURCHASE, (ART_19_9,))
    if request.reimbursed_under_art_18:
        return _not_eligible(request, ReasonCode.REIMBURSED_UNDER_ART_18, (ART_19_1,))
    if request.cause in EXCLUDED_CAUSES:
        reason, reference = EXCLUDED_CAUSES[request.cause]
        return _not_eligible(request, reason, (ART_19_10, reference, DB_9_2_1))
    if request.delay_minutes < DELAY_25_PERCENT:
        return _not_eligible(request, ReasonCode.BELOW_60_MINUTES, (ART_19_1, DB_9_2_1))

    references: list[LegalReference] = []
    notes: list[str] = []
    base_price = _cents(request.ticket_price_eur)

    flat = FLAT_RATES.get((request.ticket_kind, request.travel_class))
    if flat is not None:
        flat_rate, reference = flat
        percentage = FLAT_RATE_CAP_PERCENT
        cap = base_price * FLAT_RATE_CAP_PERCENT / 100
        compensation = _cents(min(flat_rate, cap))
        references += [reference, DB_9_2_1, ART_19_1]
        notes.append(FLAT_RATE_NOTE)
    else:
        if request.ticket_kind is TicketKind.RETURN:
            base_price = _cents(base_price / 2)
            references.append(ART_19_3)
            notes.append(RETURN_NOTE)
        if request.delay_minutes >= DELAY_50_PERCENT:
            percentage, band = 50, ART_19_1_B
        else:
            percentage, band = 25, ART_19_1_A
        compensation = _cents(base_price * percentage / 100)
        references += [band, DB_9_2_1]

    if compensation < MINIMUM_PAYOUT_EUR:
        return Compensation(
            eligible=True,
            computable=True,
            percentage=percentage,
            base_price_eur=base_price,
            compensation_eur=compensation,
            payout_eur=Decimal("0.00"),
            reason=ReasonCode.BELOW_MINIMUM_PAYOUT,
            references=(*references, ART_19_8),
            notes=tuple(notes),
            confirmation_token=None,
        )
    return Compensation(
        eligible=True,
        computable=True,
        percentage=percentage,
        base_price_eur=base_price,
        compensation_eur=compensation,
        payout_eur=compensation,
        reason=ReasonCode.ELIGIBLE,
        references=tuple(references),
        notes=tuple(notes),
        confirmation_token=confirmation_token(request, compensation),
    )
