import re
from dataclasses import dataclass

from immo_ne_collector.models import SitnStatus


@dataclass(frozen=True)
class SitnEligibility:
    eligible: bool
    needs_completion: bool
    completion_reason: str | None
    sitn_status: str


def assess_sitn_eligibility(address_full: str | None, city: str | None) -> SitnEligibility:
    """Return SITN eligibility without making any external call."""
    has_city = bool(city and city.strip())
    has_address = bool(address_full and address_full.strip())
    has_number = bool(address_full and re.search(r"\b\d+[a-zA-Z]?\b", address_full))
    has_street_text = bool(address_full and re.search(r"[A-Za-z]{3,}", address_full))

    if has_city and has_address and has_number and has_street_text:
        return SitnEligibility(
            eligible=True,
            needs_completion=False,
            completion_reason=None,
            sitn_status=SitnStatus.NOT_RUN,
        )

    return SitnEligibility(
        eligible=False,
        needs_completion=True,
        completion_reason="Adresse manquante",
        sitn_status=SitnStatus.NOT_ELIGIBLE_MISSING_ADDRESS,
    )


async def enrich_with_sitn(address_full: str | None, city: str | None) -> dict:
    eligibility = assess_sitn_eligibility(address_full, city)
    if not eligibility.eligible:
        return {
            "sitn_eligible": eligibility.eligible,
            "needs_completion": eligibility.needs_completion,
            "completion_reason": eligibility.completion_reason,
            "sitn_status": eligibility.sitn_status,
        }

    # TODO: Implementer l'appel SITN apres validation technique et legale.
    return {"sitn_eligible": True, "sitn_status": SitnStatus.NOT_RUN}
