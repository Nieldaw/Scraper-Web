from decimal import Decimal

from immo_ne_collector.scrapers.anibis_pagination import anibis_has_next_page, jittered_delay
from immo_ne_collector.services.normalization import (
    split_postal_and_city,
    validate_sale_price,
)


def test_aberrant_prices_are_discarded():
    assert validate_sale_price(Decimal("1"), None) == (None, "price_too_low")
    assert validate_sale_price(Decimal("900000000"), None) == (None, "price_too_high")
    assert validate_sale_price(Decimal("650000"), Decimal("100")) == (Decimal("650000"), None)


def test_price_per_m2_is_flagged_but_kept():
    price, flag = validate_sale_price(Decimal("100000"), Decimal("1000"))
    assert price == Decimal("100000") and flag == "price_per_m2_low"


def test_city_from_postal_code_text():
    assert split_postal_and_city("2000 Neuchâtel") == ("2000", "Neuchâtel")
    assert split_postal_and_city(None, "Rue du Lac 3, 1400 Yverdon-les-Bains") == (
        "1400",
        "Yverdon-les-Bains",
    )
    assert split_postal_and_city("Neuchâtel") == (None, None)


def test_next_page_detection():
    active = '<nav aria-label="pagination navigation"><button aria-label="Go to next page"></button></nav>'
    off = (
        '<nav aria-label="pagination navigation">'
        '<button class="Mui-disabled" disabled aria-label="Go to next page"></button></nav>'
    )
    assert anibis_has_next_page(active) is True
    assert anibis_has_next_page(off) is False
    assert anibis_has_next_page("<html></html>") is False


def test_jittered_delay_range():
    assert jittered_delay(0) == 0
    assert all(0.75 <= jittered_delay(1.0) <= 1.75 for _ in range(50))
