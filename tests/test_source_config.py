import pytest

from immo_ne_collector.services.source_config import (
    DEFAULT_ANIBIS_GE_SALE_URL,
    DEFAULT_ANIBIS_JU_SALE_URL,
    DEFAULT_ANIBIS_NE_SALE_URL,
    DEFAULT_ANIBIS_VD_SALE_URL,
    DEFAULT_ANIBIS_VS_SALE_URL,
    DEFAULT_LOOKMOVE_FR_SALE_URL,
    DEFAULT_LOOKMOVE_GE_SALE_URL,
    DEFAULT_LOOKMOVE_JU_SALE_URL,
    DEFAULT_LOOKMOVE_NE_SALE_URL,
    DEFAULT_LOOKMOVE_VD_SALE_URL,
    DEFAULT_LOOKMOVE_VS_SALE_URL,
    ROMANDY_CANTONS,
    get_sale_search_url,
    get_sale_source_config,
    infer_detected_canton,
    list_sale_source_configs,
)


def test_source_config_contains_romandy_cantons() -> None:
    assert ROMANDY_CANTONS == ("GE", "VD", "NE", "JU", "FR", "VS")


def test_source_config_returns_enabled_urls() -> None:
    assert get_sale_search_url(source="anibis", canton="GE") == DEFAULT_ANIBIS_GE_SALE_URL
    assert get_sale_search_url(source="anibis", canton="VD") == DEFAULT_ANIBIS_VD_SALE_URL
    assert get_sale_search_url(source="anibis", canton="NE") == DEFAULT_ANIBIS_NE_SALE_URL
    assert get_sale_search_url(source="anibis", canton="JU") == DEFAULT_ANIBIS_JU_SALE_URL
    assert get_sale_search_url(source="anibis", canton="VS") == DEFAULT_ANIBIS_VS_SALE_URL
    assert get_sale_search_url(source="lookmove", canton="GE") == DEFAULT_LOOKMOVE_GE_SALE_URL
    assert get_sale_search_url(source="lookmove", canton="VD") == DEFAULT_LOOKMOVE_VD_SALE_URL
    assert get_sale_search_url(source="lookmove", canton="NE") == DEFAULT_LOOKMOVE_NE_SALE_URL
    assert get_sale_search_url(source="lookmove", canton="JU") == DEFAULT_LOOKMOVE_JU_SALE_URL
    assert get_sale_search_url(source="lookmove", canton="FR") == DEFAULT_LOOKMOVE_FR_SALE_URL
    assert get_sale_search_url(source="lookmove", canton="VS") == DEFAULT_LOOKMOVE_VS_SALE_URL


def test_source_config_raises_for_unsupported_source() -> None:
    with pytest.raises(ValueError, match="not supported"):
        get_sale_search_url(source="unknown_source", canton="NE")


def test_source_config_raises_for_disabled_anibis_canton() -> None:
    with pytest.raises(ValueError, match="configured but disabled"):
        get_sale_search_url(source="anibis", canton="FR")


def test_get_sale_source_config_disabled_entry_contains_note() -> None:
    config = get_sale_source_config(source="anibis", canton="FR")
    assert config.enabled is False
    assert config.url is not None
    assert config.note is not None


def test_list_sale_source_configs_returns_all_romandy_entries() -> None:
    rows = list_sale_source_configs(sources=["anibis", "lookmove"], cantons=list(ROMANDY_CANTONS))
    assert len(rows) == 12


def test_infer_detected_canton_from_url_city_and_postal_code() -> None:
    detected, reason = infer_detected_canton(
        url="https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans-geneve/1",
        city="Geneve",
        postal_code="1201",
    )
    assert detected == "GE"
    assert reason in {"url", "city", "postal_code"}


def test_infer_detected_canton_returns_unknown_on_ambiguous_data() -> None:
    detected, reason = infer_detected_canton(
        url="https://www.example.test/immobilier/acheter/annonce/1",
        city=None,
        postal_code=None,
    )
    assert detected == "unknown"
    assert reason == "unknown"


def test_infer_detected_canton_from_url_city_slug_keyword() -> None:
    detected, reason = infer_detected_canton(
        url="https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans-le-locle,14377864",
        city=None,
        postal_code=None,
    )
    assert detected == "NE"
    assert reason == "url"
