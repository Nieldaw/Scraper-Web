"""Formulaire de mandat et filtres : cases à cocher, listes déroulantes, curseurs."""

import re
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.main import app
from immo_ne_collector.models import Property
from immo_ne_collector.services.filter_options import (
    DEFAULT_PRICE,
    PROPERTY_TYPE_CHOICES,
    FilterOptions,
    SliderBounds,
    _nice_bounds,
    with_current_option,
)
from immo_ne_collector.services.source_config import ROMANDY_CANTONS
from immo_ne_collector.web import routes
from immo_ne_collector.web.routes import _csv_list, _num_str, _sliders

OPTIONS = FilterOptions(
    cities=["Bevaix", "Martigny", "Neuchâtel"],
    cantons=ROMANDY_CANTONS,
    property_types=PROPERTY_TYPE_CHOICES,
    price=SliderBounds(0, 3_000_000, 10_000),
    rooms=SliderBounds(1, 10, 0.5),
    area=SliderBounds(0, 500, 5),
)


# --- logique pure (sans base) ----------------------------------------------------------------
def test_types_sont_appartement_maison_terrain():
    assert [v for v, _ in PROPERTY_TYPE_CHOICES] == ["appartement", "maison", "terrain"]


def test_csv_list_accepte_champs_repetes_et_texte():
    assert _csv_list(["Sion", "Bevaix"]) == ["Sion", "Bevaix"]
    assert _csv_list("Sion, Bevaix") == ["Sion", "Bevaix"]
    assert _csv_list(["Sion, Bevaix", "Nyon"]) == ["Sion", "Bevaix", "Nyon"]
    assert _csv_list(None) == [] and _csv_list([]) == []


def test_num_str_comparable_aux_options():
    assert _num_str(300000.0) == "300000"
    assert _num_str(1_500_000.0) == "1500000"
    assert _num_str(4.5) == "4.5"
    assert _num_str(None) == ""


def test_with_current_option_ajoute_la_valeur_inconnue():
    assert with_current_option([1, 2, 3], 2) == [1, 2, 3]
    assert with_current_option([1, 2, 3], None) == [1, 2, 3]
    assert with_current_option([100, 300], 200) == [100, 200, 300]


def test_slider_bounds_incluent_les_valeurs_prerremplies():
    b = SliderBounds(0, 1_000_000, 10_000).including(None, 2_340_000)
    assert b.high == 2_340_000 and b.low == 0
    assert SliderBounds(1, 10, 0.5).including(0.5, 4).low == 0.5


def test_nice_bounds_arrondit_et_garde_un_defaut():
    assert _nice_bounds(None, None, 10_000, DEFAULT_PRICE) == DEFAULT_PRICE
    b = _nice_bounds(0, 1_234_567, 10_000, DEFAULT_PRICE)
    assert (b.low, b.high) == (0, 1_240_000)
    same = _nice_bounds(5, 5, 5, DEFAULT_PRICE)
    assert same.high > same.low


def test_sliders_utilisent_les_valeurs_du_formulaire():
    sl = {
        s["key"]: s
        for s in _sliders(OPTIONS, {"min_price_chf": "400000", "max_price_chf": "600000"})
    }
    assert (sl["price"]["min_value"], sl["price"]["max_value"]) == (400000, 600000)
    assert (sl["rooms"]["min_value"], sl["rooms"]["max_value"]) == (1, 10)  # bornes = indifférent


# --- pages rendues sans base (accès base simulés) -------------------------------------------
@pytest.fixture
def client_sans_base(monkeypatch):
    async def fake_options(_session):
        return OPTIONS

    async def fake_mandates(_session, **_kw):
        return []

    async def fake_search(_session, filters, **_kw):
        fake_search.filters = filters
        return [], 0

    monkeypatch.setattr(routes, "load_filter_options", fake_options)
    monkeypatch.setattr(routes, "list_search_mandates", fake_mandates)
    monkeypatch.setattr(routes, "search_properties", fake_search)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), fake_search


async def test_formulaire_mandat_a_cases_liste_et_curseurs(client_sans_base):
    client, _ = client_sans_base
    html = (await client.get("/mandates")).text
    assert 'name="property_types" value="appartement"' in html
    assert 'name="property_types" value="maison"' in html
    assert 'name="property_types" value="terrain"' in html
    for city in OPTIONS.cities:
        assert f'name="cities" value="{city}"' in html
    assert html.count('type="range"') == 6  # 3 curseurs doubles
    for name in (
        "min_price_chf",
        "max_price_chf",
        "min_rooms",
        "max_rooms",
        "min_living_area_m2",
        "max_living_area_m2",
    ):
        assert f'name="{name}"' in html
    # plus de champs texte libres pour villes / types
    assert not re.search(r'<input name="(cities|property_types)"', html)
    assert "mandate_form.js" in html
    # HTMX valide tout <form> déclencheur : l'aperçu doit partir d'un div, pas du formulaire
    assert 'hx-include="find form"' in html
    assert not re.search(r"<form[^>]*hx-get", html)


async def test_formulaire_mandat_prerempli_coche_et_positionne(client_sans_base, monkeypatch):
    client, _ = client_sans_base
    row = Property(
        city="Martigny",
        property_type="maison",
        price_chf=Decimal("500000"),
        rooms=Decimal("5"),
        living_area_m2=Decimal("120"),
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )

    async def fake_get(_session, _id):
        return row

    monkeypatch.setattr(routes, "get_property", fake_get)
    html = (await client.get("/mandates?from_property=00000000-0000-0000-0000-000000000001")).text
    assert re.search(r'name="cities" value="Martigny" checked', html)
    assert re.search(r'name="property_types" value="maison" checked', html)
    assert not re.search(r'name="property_types" value="terrain" checked', html)
    assert 'data-hidden="min" value="400000"' in html


async def test_filtres_proprietes_sont_des_listes(client_sans_base):
    client, fake_search = client_sans_base
    html = (
        await client.get(
            "/properties?city=Martigny&property_type=maison&min_price=300000&min_rooms=3.5"
        )
    ).text
    assert '<select name="city"' in html and '<select name="canton"' in html
    assert '<select name="property_type"' in html
    assert '<select name="min_price"' in html and '<select name="max_price"' in html
    assert '<select name="min_rooms"' in html
    assert not re.search(r'<input[^>]*name="(city|canton|min_price|max_price|min_rooms)"', html)
    assert re.search(r'<option value="Martigny" selected', html)
    assert re.search(r'<option value="maison" selected', html)
    assert re.search(r'<option value="300000" selected', html)
    assert re.search(r'<option value="3.5" selected', html)
    assert fake_search.filters.property_type == "maison"


async def test_valeur_hors_palier_reste_selectionnee(client_sans_base):
    client, _ = client_sans_base
    html = (await client.get("/properties?min_price=350000")).text
    assert re.search(r'<option value="350000" selected', html)


# --- avec base : le filtre par type agit vraiment ----------------------------------------------
@pytest.mark.db
async def test_filtre_type_et_options_en_base():
    from immo_ne_collector.services.filter_options import load_filter_options
    from immo_ne_collector.services.property_queries import PropertyFilters, search_properties

    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        for city, ptype, price in (
            ("Sion", "maison", 700000),
            ("Sion", "terrain", 200000),
            ("Nyon", "appartement", 900000),
        ):
            session.add(
                Property(
                    city=city,
                    property_type=ptype,
                    price_chf=price,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
        await session.commit()
        rows, total = await search_properties(session, PropertyFilters(property_type="Maison"))
        assert total == 1 and rows[0].city == "Sion"
        opts = await load_filter_options(session)
        assert opts.cities == ["Nyon", "Sion"]
        assert opts.price.high >= 900000
