from decimal import Decimal

from immo_ne_collector.services.deduplication import ListingCandidate, score_pair


def test_score_pair_merges_obvious_duplicate() -> None:
    a = ListingCandidate(
        title="Bel appartement 4.5 pieces",
        property_type="appartement",
        city="Neuchatel",
        price_chf=Decimal("850000"),
        rooms=Decimal("4.5"),
        living_area_m2=Decimal("110"),
    )
    b = ListingCandidate(
        title="Appartement 4.5 pieces a Neuchatel",
        property_type="appartement",
        city="Neuchatel",
        price_chf=Decimal("855000"),
        rooms=Decimal("4.5"),
        living_area_m2=Decimal("112"),
    )
    result = score_pair(a, b)
    assert result.should_merge is True
    assert result.score >= 0.82


def test_score_pair_does_not_merge_different_city() -> None:
    a = ListingCandidate(title="Maison", property_type="maison", city="Neuchatel")
    b = ListingCandidate(title="Maison", property_type="maison", city="La Chaux-de-Fonds")
    result = score_pair(a, b)
    assert result.should_merge is False


def test_score_pair_does_not_merge_when_detected_canton_differs() -> None:
    a = ListingCandidate(
        title="Appartement",
        property_type="appartement",
        city="Neuchatel",
        detected_canton="NE",
    )
    b = ListingCandidate(
        title="Appartement",
        property_type="appartement",
        city="Geneve",
        detected_canton="GE",
    )
    result = score_pair(a, b)
    assert result.should_merge is False
    assert result.reasons == ["canton_mismatch"]
