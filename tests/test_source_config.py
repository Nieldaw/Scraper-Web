import pytest

from immo_ne_collector.services.source_config import (
    DEFAULT_ANIBIS_BE_SALE_URL_FUTURE,
    DEFAULT_ANIBIS_FR_SALE_URL_CANDIDATE,
    DEFAULT_ANIBIS_GE_SALE_URL,
    DEFAULT_ANIBIS_JU_SALE_URL,
    DEFAULT_ANIBIS_NE_SALE_URL,
    DEFAULT_ANIBIS_VD_SALE_URL,
    DEFAULT_ANIBIS_VS_SALE_URL,
    DEFAULT_HOMEGATE_FR_SALE_LAND_URL,
    DEFAULT_HOMEGATE_FR_SALE_RESIDENTIAL_URL,
    DEFAULT_HOMEGATE_GE_SALE_LAND_URL,
    DEFAULT_HOMEGATE_GE_SALE_RESIDENTIAL_URL,
    DEFAULT_HOMEGATE_JU_SALE_LAND_URL,
    DEFAULT_HOMEGATE_JU_SALE_RESIDENTIAL_URL,
    DEFAULT_HOMEGATE_NE_SALE_LAND_URL,
    DEFAULT_HOMEGATE_NE_SALE_RESIDENTIAL_URL,
    DEFAULT_HOMEGATE_VD_SALE_LAND_URL,
    DEFAULT_HOMEGATE_VD_SALE_RESIDENTIAL_URL,
    DEFAULT_HOMEGATE_VS_SALE_LAND_URL,
    DEFAULT_HOMEGATE_VS_SALE_RESIDENTIAL_URL,
    DEFAULT_LOOKMOVE_FR_SALE_URL,
    DEFAULT_LOOKMOVE_GE_SALE_URL,
    DEFAULT_LOOKMOVE_JU_SALE_URL,
    DEFAULT_LOOKMOVE_NE_SALE_URL,
    DEFAULT_LOOKMOVE_VD_SALE_URL,
    DEFAULT_LOOKMOVE_VS_SALE_URL,
    DEFAULT_IMMOSCOUT_FR_SALE_LAND_URL,
    DEFAULT_IMMOSCOUT_FR_SALE_RESIDENTIAL_URL,
    DEFAULT_IMMOSCOUT_GE_SALE_LAND_URL,
    DEFAULT_IMMOSCOUT_GE_SALE_RESIDENTIAL_URL,
    DEFAULT_IMMOSCOUT_JU_SALE_LAND_URL,
    DEFAULT_IMMOSCOUT_JU_SALE_RESIDENTIAL_URL,
    DEFAULT_IMMOSCOUT_NE_SALE_LAND_URL,
    DEFAULT_IMMOSCOUT_NE_SALE_RESIDENTIAL_URL,
    DEFAULT_IMMOSCOUT_VD_SALE_LAND_URL,
    DEFAULT_IMMOSCOUT_VD_SALE_RESIDENTIAL_URL,
    DEFAULT_IMMOSCOUT_VS_SALE_LAND_URL,
    DEFAULT_IMMOSCOUT_VS_SALE_RESIDENTIAL_URL,
    ROMANDY_CANTONS,
    SUPPORTED_CANTONS,
    get_sale_search_url,
    get_sale_source_config,
    get_sale_source_urls,
    infer_detected_canton,
    list_sale_source_configs,
)


def test_source_config_contains_romandy_cantons() -> None:
    assert ROMANDY_CANTONS == ("GE", "VD", "NE", "JU", "FR", "VS")
    assert "BE" not in ROMANDY_CANTONS
    assert "BE" not in SUPPORTED_CANTONS


def test_source_config_returns_enabled_urls() -> None:
    assert get_sale_search_url(source="anibis", canton="FR") == DEFAULT_ANIBIS_FR_SALE_URL_CANDIDATE
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
    with pytest.raises(ValueError, match="configured but disabled"):
        get_sale_search_url(source="homegate", canton="GE")
    with pytest.raises(ValueError, match="configured but disabled"):
        get_sale_search_url(source="immoscout", canton="GE")


def test_source_config_raises_for_unsupported_source() -> None:
    with pytest.raises(ValueError, match="not supported"):
        get_sale_search_url(source="unknown_source", canton="NE")


def test_get_sale_source_config_anibis_fr_entry_contains_note() -> None:
    config = get_sale_source_config(source="anibis", canton="FR")
    assert config.enabled is True
    assert config.url is not None
    assert config.note is not None


def test_list_sale_source_configs_returns_all_romandy_entries() -> None:
    rows = list_sale_source_configs(
        sources=["anibis", "lookmove", "homegate", "immoscout"],
        cantons=list(ROMANDY_CANTONS),
    )
    assert len(rows) == 24


def test_source_config_homegate_contains_romandy_urls_and_starts_disabled() -> None:
    assert get_sale_source_config(source="homegate", canton="GE").url == DEFAULT_HOMEGATE_GE_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="homegate", canton="VD").url == DEFAULT_HOMEGATE_VD_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="homegate", canton="NE").url == DEFAULT_HOMEGATE_NE_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="homegate", canton="JU").url == DEFAULT_HOMEGATE_JU_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="homegate", canton="FR").url == DEFAULT_HOMEGATE_FR_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="homegate", canton="VS").url == DEFAULT_HOMEGATE_VS_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="homegate", canton="NE").enabled is False

    ge_urls = get_sale_source_urls(source="homegate", canton="GE")
    assert [item.url_kind for item in ge_urls] == ["residential", "land"]
    assert ge_urls[0].url == DEFAULT_HOMEGATE_GE_SALE_RESIDENTIAL_URL
    assert ge_urls[1].url == DEFAULT_HOMEGATE_GE_SALE_LAND_URL

    vd_urls = get_sale_source_urls(source="homegate", canton="VD")
    assert vd_urls[0].url == DEFAULT_HOMEGATE_VD_SALE_RESIDENTIAL_URL
    assert vd_urls[1].url == DEFAULT_HOMEGATE_VD_SALE_LAND_URL

    ne_urls = get_sale_source_urls(source="homegate", canton="NE")
    assert ne_urls[0].url == DEFAULT_HOMEGATE_NE_SALE_RESIDENTIAL_URL
    assert ne_urls[1].url == DEFAULT_HOMEGATE_NE_SALE_LAND_URL

    ju_urls = get_sale_source_urls(source="homegate", canton="JU")
    assert ju_urls[0].url == DEFAULT_HOMEGATE_JU_SALE_RESIDENTIAL_URL
    assert ju_urls[1].url == DEFAULT_HOMEGATE_JU_SALE_LAND_URL

    fr_urls = get_sale_source_urls(source="homegate", canton="FR")
    assert fr_urls[0].url == DEFAULT_HOMEGATE_FR_SALE_RESIDENTIAL_URL
    assert fr_urls[1].url == DEFAULT_HOMEGATE_FR_SALE_LAND_URL

    vs_urls = get_sale_source_urls(source="homegate", canton="VS")
    assert vs_urls[0].url == DEFAULT_HOMEGATE_VS_SALE_RESIDENTIAL_URL
    assert vs_urls[1].url == DEFAULT_HOMEGATE_VS_SALE_LAND_URL


def test_source_config_immoscout_contains_romandy_urls_and_starts_disabled() -> None:
    assert get_sale_source_config(source="immoscout", canton="GE").url == DEFAULT_IMMOSCOUT_GE_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="immoscout", canton="VD").url == DEFAULT_IMMOSCOUT_VD_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="immoscout", canton="NE").url == DEFAULT_IMMOSCOUT_NE_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="immoscout", canton="JU").url == DEFAULT_IMMOSCOUT_JU_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="immoscout", canton="FR").url == DEFAULT_IMMOSCOUT_FR_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="immoscout", canton="VS").url == DEFAULT_IMMOSCOUT_VS_SALE_RESIDENTIAL_URL
    assert get_sale_source_config(source="immoscout", canton="NE").enabled is False

    ge_urls = get_sale_source_urls(source="immoscout", canton="GE")
    assert [item.url_kind for item in ge_urls] == ["residential", "land"]
    assert ge_urls[0].url == DEFAULT_IMMOSCOUT_GE_SALE_RESIDENTIAL_URL
    assert ge_urls[1].url == DEFAULT_IMMOSCOUT_GE_SALE_LAND_URL

    vd_urls = get_sale_source_urls(source="immoscout", canton="VD")
    assert vd_urls[0].url == DEFAULT_IMMOSCOUT_VD_SALE_RESIDENTIAL_URL
    assert vd_urls[1].url == DEFAULT_IMMOSCOUT_VD_SALE_LAND_URL

    ne_urls = get_sale_source_urls(source="immoscout", canton="NE")
    assert ne_urls[0].url == DEFAULT_IMMOSCOUT_NE_SALE_RESIDENTIAL_URL
    assert ne_urls[1].url == DEFAULT_IMMOSCOUT_NE_SALE_LAND_URL

    ju_urls = get_sale_source_urls(source="immoscout", canton="JU")
    assert ju_urls[0].url == DEFAULT_IMMOSCOUT_JU_SALE_RESIDENTIAL_URL
    assert ju_urls[1].url == DEFAULT_IMMOSCOUT_JU_SALE_LAND_URL

    fr_urls = get_sale_source_urls(source="immoscout", canton="FR")
    assert fr_urls[0].url == DEFAULT_IMMOSCOUT_FR_SALE_RESIDENTIAL_URL
    assert fr_urls[1].url == DEFAULT_IMMOSCOUT_FR_SALE_LAND_URL

    vs_urls = get_sale_source_urls(source="immoscout", canton="VS")
    assert vs_urls[0].url == DEFAULT_IMMOSCOUT_VS_SALE_RESIDENTIAL_URL
    assert vs_urls[1].url == DEFAULT_IMMOSCOUT_VS_SALE_LAND_URL


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


def test_source_config_exposes_be_future_url_but_keeps_it_out_of_supported_cantons() -> None:
    assert "immobilier-berne-appartements-maisons-terrains-acheter" in DEFAULT_ANIBIS_BE_SALE_URL_FUTURE
    with pytest.raises(ValueError, match="not supported in MVP"):
        get_sale_search_url(source="anibis", canton="BE")
