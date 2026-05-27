import pytest

from immo_ne_collector.services.source_config import (
    DEFAULT_ANIBIS_NE_SALE_URL,
    DEFAULT_LOOKMOVE_NE_SALE_URL,
    get_sale_search_url,
)


def test_source_config_returns_ne_urls() -> None:
    assert get_sale_search_url(source="anibis", canton="NE") == DEFAULT_ANIBIS_NE_SALE_URL
    assert get_sale_search_url(source="lookmove", canton="NE") == DEFAULT_LOOKMOVE_NE_SALE_URL


def test_source_config_raises_for_unsupported_source() -> None:
    with pytest.raises(ValueError, match="not supported"):
        get_sale_search_url(source="unknown_source", canton="NE")


def test_source_config_raises_for_unconfigured_canton() -> None:
    with pytest.raises(ValueError, match="No configured sale URL"):
        get_sale_search_url(source="anibis", canton="VD")

