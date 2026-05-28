from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from rapidfuzz import fuzz


@dataclass(frozen=True)
class ListingCandidate:
    title: str | None = None
    property_type: str | None = None
    city: str | None = None
    price_chf: Decimal | None = None
    rooms: Decimal | None = None
    living_area_m2: Decimal | None = None
    address_full: str | None = None
    detected_canton: str | None = None


@dataclass(frozen=True)
class DeduplicationResult:
    should_merge: bool
    score: float
    reasons: list[str] = field(default_factory=list)


MERGE_THRESHOLD = 0.82
MATCH_THRESHOLD = 0.88
AMBIGUOUS_THRESHOLD = 0.72


def _relative_close(a: Decimal | None, b: Decimal | None, tolerance: float) -> bool:
    if a is None or b is None or a == 0 or b == 0:
        return False
    diff = abs(float(a - b)) / max(float(a), float(b))
    return diff <= tolerance


def score_pair(a: ListingCandidate, b: ListingCandidate) -> DeduplicationResult:
    if (
        a.detected_canton
        and b.detected_canton
        and a.detected_canton != "unknown"
        and b.detected_canton != "unknown"
        and a.detected_canton != b.detected_canton
    ):
        return DeduplicationResult(
            should_merge=False,
            score=0.0,
            reasons=["canton_mismatch"],
        )

    score = 0.0
    weight = 0.0
    reasons: list[str] = []

    def add(points: float, max_points: float, reason: str | None = None) -> None:
        nonlocal score, weight
        score += points
        weight += max_points
        if reason and points > 0:
            reasons.append(reason)

    if a.city and b.city:
        add(1.0 if a.city.lower() == b.city.lower() else 0.0, 1.0, "same_city")

    if a.property_type and b.property_type:
        add(
            1.0 if a.property_type.lower() == b.property_type.lower() else 0.0,
            1.0,
            "same_property_type",
        )

    if a.address_full and b.address_full:
        similarity = fuzz.token_sort_ratio(a.address_full, b.address_full) / 100
        add(similarity, 1.5, "similar_address" if similarity >= 0.9 else None)

    if a.title and b.title:
        similarity = fuzz.token_sort_ratio(a.title, b.title) / 100
        add(similarity, 1.0, "similar_title" if similarity >= 0.85 else None)

    if _relative_close(a.price_chf, b.price_chf, 0.08):
        add(1.0, 1.0, "close_price")
    elif a.price_chf is not None and b.price_chf is not None:
        add(0.0, 1.0)

    if _relative_close(a.living_area_m2, b.living_area_m2, 0.08):
        add(1.0, 1.0, "close_area")
    elif a.living_area_m2 is not None and b.living_area_m2 is not None:
        add(0.0, 1.0)

    if a.rooms is not None and b.rooms is not None:
        add(1.0 if abs(float(a.rooms - b.rooms)) <= 0.5 else 0.0, 1.0, "close_rooms")

    final_score = score / weight if weight else 0.0
    return DeduplicationResult(
        should_merge=final_score >= MERGE_THRESHOLD,
        score=round(final_score, 4),
        reasons=reasons,
    )


class MatchOutcome(StrEnum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class MatchDecision:
    matched_property_id: UUID | None
    score: float
    decision: MatchOutcome
    reasons: list[str] = field(default_factory=list)


def _score_for_match(a: ListingCandidate, b: ListingCandidate) -> tuple[float, list[str], int]:
    reasons: list[str] = []
    if (
        a.detected_canton
        and b.detected_canton
        and a.detected_canton != "unknown"
        and b.detected_canton != "unknown"
        and a.detected_canton != b.detected_canton
    ):
        return 0.0, ["canton_mismatch"], 0

    if a.city and b.city and a.city.lower() != b.city.lower():
        return 0.0, ["city_mismatch"], 0
    if a.property_type and b.property_type and a.property_type.lower() != b.property_type.lower():
        return 0.0, ["property_type_mismatch"], 0

    weighted_score = 0.0
    max_weight = 0.0
    evidence_count = 0

    if a.address_full and b.address_full:
        evidence_count += 1
        similarity = fuzz.token_sort_ratio(a.address_full, b.address_full) / 100
        max_weight += 2.0
        weighted_score += similarity * 2.0
        if similarity >= 0.94:
            reasons.append("address_very_similar")
        elif similarity >= 0.86:
            reasons.append("address_similar")

    if a.title and b.title:
        evidence_count += 1
        similarity = fuzz.token_sort_ratio(a.title, b.title) / 100
        max_weight += 1.0
        weighted_score += similarity
        if similarity >= 0.86:
            reasons.append("title_similar")

    if a.price_chf is not None and b.price_chf is not None:
        evidence_count += 1
        max_weight += 1.0
        if _relative_close(a.price_chf, b.price_chf, 0.08):
            weighted_score += 1.0
            reasons.append("price_close")

    if a.living_area_m2 is not None and b.living_area_m2 is not None:
        evidence_count += 1
        max_weight += 1.0
        if _relative_close(a.living_area_m2, b.living_area_m2, 0.10):
            weighted_score += 1.0
            reasons.append("area_close")

    if a.rooms is not None and b.rooms is not None:
        evidence_count += 1
        max_weight += 1.0
        if abs(float(a.rooms - b.rooms)) <= 0.5:
            weighted_score += 1.0
            reasons.append("rooms_close")

    if max_weight == 0:
        return 0.0, reasons, evidence_count
    return round(weighted_score / max_weight, 4), reasons, evidence_count


def decide_property_match(
    listing: ListingCandidate,
    candidates: list[tuple[UUID, ListingCandidate]],
) -> MatchDecision:
    if not candidates:
        return MatchDecision(
            matched_property_id=None,
            score=0.0,
            decision=MatchOutcome.NO_MATCH,
            reasons=["no_candidates"],
        )

    ranked: list[tuple[UUID, float, list[str], int]] = []
    for property_id, candidate in candidates:
        score, reasons, evidence_count = _score_for_match(listing, candidate)
        if reasons in (["city_mismatch"], ["property_type_mismatch"], ["canton_mismatch"]):
            continue
        ranked.append((property_id, score, reasons, evidence_count))

    if not ranked:
        return MatchDecision(
            matched_property_id=None,
            score=0.0,
            decision=MatchOutcome.NO_MATCH,
            reasons=["hard_mismatch_on_canton_or_city_or_type"],
        )

    ranked.sort(key=lambda row: row[1], reverse=True)
    top_id, top_score, top_reasons, top_evidence = ranked[0]

    if top_evidence < 2:
        return MatchDecision(
            matched_property_id=None,
            score=top_score,
            decision=MatchOutcome.AMBIGUOUS if top_score >= AMBIGUOUS_THRESHOLD else MatchOutcome.NO_MATCH,
            reasons=[*top_reasons, "insufficient_evidence"],
        )

    if top_score >= MATCH_THRESHOLD and top_evidence >= 3:
        if len(ranked) > 1 and ranked[1][1] >= AMBIGUOUS_THRESHOLD and abs(top_score - ranked[1][1]) < 0.03:
            return MatchDecision(
                matched_property_id=None,
                score=top_score,
                decision=MatchOutcome.AMBIGUOUS,
                reasons=[*top_reasons, "multiple_close_candidates"],
            )
        return MatchDecision(
            matched_property_id=top_id,
            score=top_score,
            decision=MatchOutcome.MATCH,
            reasons=top_reasons or ["high_confidence_match"],
        )

    if top_score >= AMBIGUOUS_THRESHOLD:
        return MatchDecision(
            matched_property_id=None,
            score=top_score,
            decision=MatchOutcome.AMBIGUOUS,
            reasons=top_reasons or ["score_in_ambiguous_range"],
        )

    return MatchDecision(
        matched_property_id=None,
        score=top_score,
        decision=MatchOutcome.NO_MATCH,
        reasons=top_reasons or ["score_too_low"],
    )
