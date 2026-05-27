from immo_ne_collector.models import SitnStatus
from immo_ne_collector.services.sitn import assess_sitn_eligibility


def test_sitn_not_eligible_without_address() -> None:
    result = assess_sitn_eligibility(None, "Neuchatel")
    assert result.eligible is False
    assert result.needs_completion is True
    assert result.completion_reason == "Adresse manquante"
    assert result.sitn_status == SitnStatus.NOT_ELIGIBLE_MISSING_ADDRESS


def test_sitn_not_eligible_without_number() -> None:
    result = assess_sitn_eligibility("Rue du Seyon", "Neuchatel")
    assert result.eligible is False


def test_sitn_eligible_with_full_address() -> None:
    result = assess_sitn_eligibility("Rue du Seyon 12", "Neuchatel")
    assert result.eligible is True
    assert result.needs_completion is False
    assert result.sitn_status == SitnStatus.NOT_RUN
