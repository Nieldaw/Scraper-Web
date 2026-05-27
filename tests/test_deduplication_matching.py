from decimal import Decimal
from uuid import uuid4

from immo_ne_collector.services.deduplication import (
    ListingCandidate,
    MatchOutcome,
    decide_property_match,
)


def test_decide_property_match_obvious_cross_source_match() -> None:
    listing = ListingCandidate(
        title="Appartement 4.5 pieces a Neuchatel",
        property_type="appartement",
        city="Neuchatel",
        price_chf=Decimal("850000"),
        rooms=Decimal("4.5"),
        living_area_m2=Decimal("110"),
        address_full="Rue du Seyon 12",
    )
    candidate = ListingCandidate(
        title="Bel appartement 4.5 pieces Neuchatel",
        property_type="appartement",
        city="Neuchatel",
        price_chf=Decimal("855000"),
        rooms=Decimal("4.5"),
        living_area_m2=Decimal("112"),
        address_full="Rue du Seyon 12",
    )
    property_id = uuid4()
    decision = decide_property_match(listing, [(property_id, candidate)])

    assert decision.decision == MatchOutcome.MATCH
    assert decision.matched_property_id == property_id
    assert decision.score >= 0.88


def test_decide_property_match_no_match_when_city_differs() -> None:
    listing = ListingCandidate(city="Neuchatel", property_type="appartement")
    candidate = ListingCandidate(city="Boudry", property_type="appartement")
    decision = decide_property_match(listing, [(uuid4(), candidate)])

    assert decision.decision == MatchOutcome.NO_MATCH


def test_decide_property_match_no_match_when_property_type_differs() -> None:
    listing = ListingCandidate(city="Neuchatel", property_type="appartement")
    candidate = ListingCandidate(city="Neuchatel", property_type="maison")
    decision = decide_property_match(listing, [(uuid4(), candidate)])

    assert decision.decision == MatchOutcome.NO_MATCH


def test_decide_property_match_ambiguous_when_data_is_close_but_insufficient() -> None:
    listing = ListingCandidate(
        title="Appartement centre-ville",
        city="Neuchatel",
        property_type="appartement",
    )
    candidate = ListingCandidate(
        title="Bel appartement au centre-ville",
        city="Neuchatel",
        property_type="appartement",
    )
    decision = decide_property_match(listing, [(uuid4(), candidate)])

    assert decision.decision == MatchOutcome.AMBIGUOUS
    assert decision.matched_property_id is None


def test_decide_property_match_no_match_when_price_and_area_very_different() -> None:
    listing = ListingCandidate(
        title="Appartement 4.5 pieces a Neuchatel",
        city="Neuchatel",
        property_type="appartement",
        price_chf=Decimal("850000"),
        living_area_m2=Decimal("110"),
    )
    candidate = ListingCandidate(
        title="Appartement 4.5 pieces a Neuchatel",
        city="Neuchatel",
        property_type="appartement",
        price_chf=Decimal("1600000"),
        living_area_m2=Decimal("260"),
    )

    decision = decide_property_match(listing, [(uuid4(), candidate)])
    assert decision.decision in {MatchOutcome.NO_MATCH, MatchOutcome.AMBIGUOUS}
    assert decision.matched_property_id is None
