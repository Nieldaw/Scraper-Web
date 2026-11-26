from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.main import app
from immo_ne_collector.models import Property, PropertyStatus
from immo_ne_collector.services.property_queries import extract_image_url


@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _add(**kwargs) -> Property:
    now = datetime.now(UTC)
    values = {
        "title": "Villa test",
        "property_type": "house",
        "price_chf": Decimal("900000"),
        "rooms": Decimal("5.5"),
        "living_area_m2": Decimal("150"),
        "city": "Neuchâtel",
        "sources": ["anibis"],
        "source_urls": ["https://example.org/a"],
        "first_seen_at": now,
        "last_seen_at": now,
        "status": PropertyStatus.NEW,
        "raw_data": {},
    }
    values.update(kwargs)
    async with AsyncSessionLocal() as session:
        row = Property(**values)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


# --- extraction d'image (sans DB) -------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ({}, None),
        ({"image_url": "https://img.example/a.jpg"}, "https://img.example/a.jpg"),
        ({"image_url": "javascript:alert(1)"}, None),
        ({"image_url": "/relative.jpg"}, None),
        ({"image_url": 42}, None),
        ({"images": ["", "ftp://x/y.jpg", "http://ok.example/b.jpg"]}, "http://ok.example/b.jpg"),
        ({"photos": [{"url": "https://img.example/c.jpg"}]}, "https://img.example/c.jpg"),
    ],
)
def test_extract_image_url(raw, expected):
    assert extract_image_url(raw) == expected


# --- pages sans DB ----------------------------------------------------------------


@pytest.mark.parametrize("slug", ["analysis", "chat", "account"])
async def test_coming_soon_pages(client, slug):
    r = await client.get(f"/{slug}")
    assert r.status_code == 200
    assert "Bientôt disponible" in r.text


async def test_unknown_page_is_404(client):
    assert (await client.get("/nope")).status_code == 404


async def test_static_css_served(client):
    assert (await client.get("/static/style.css")).status_code == 200


# --- avec DB ----------------------------------------------------------------------


@pytest.mark.db
async def test_api_list_filters_and_stats(client):
    await _add(title="Villa NE", city="Neuchâtel")
    await _add(
        title="Flat GE", city="Genève", price_chf=Decimal("500000"), status=PropertyStatus.UPDATED
    )
    await _add(title="Old", city="Sion", status=PropertyStatus.REMOVED)

    r = await client.get("/api/properties")
    assert r.status_code == 200
    assert r.json()["total"] == 3

    assert (await client.get("/api/properties?status=new")).json()["total"] == 1
    assert (await client.get("/api/properties/updated")).json()["total"] == 1
    assert (await client.get("/api/properties/inactive")).json()["total"] == 1
    assert (await client.get("/api/properties?city=genève")).json()["total"] == 1
    assert (await client.get("/api/properties?q=villa")).json()["total"] == 1
    assert (await client.get("/api/properties?max_price=600000")).json()["total"] == 1

    items = (await client.get("/api/properties?sort=price_asc")).json()["items"]
    assert items[0]["price_chf"] == 500000.0

    stats = (await client.get("/api/stats")).json()
    assert stats == {"new": 1, "active": 0, "modified": 1, "inactive": 1, "total": 3}


@pytest.mark.db
async def test_api_search_escapes_like_wildcards(client):
    await _add(title="Villa")
    assert (await client.get("/api/properties?q=%25")).json()["total"] == 0


@pytest.mark.db
async def test_api_validation_and_404(client):
    assert (await client.get("/api/properties?status=bogus")).status_code == 422
    assert (await client.get("/api/properties?page_size=1000")).status_code == 422
    assert (
        await client.get("/api/properties/00000000-0000-0000-0000-000000000000")
    ).status_code == 404
    assert (await client.get("/properties/00000000-0000-0000-0000-000000000000")).status_code == 404


@pytest.mark.db
async def test_api_image_and_detail(client):
    row = await _add(raw_data={"image_url": "https://img.example/a.jpg"})
    data = (await client.get(f"/api/properties/{row.id}")).json()
    assert data["image_url"] == "https://img.example/a.jpg"
    assert data["status_label"] == "new"


@pytest.mark.db
async def test_pages_render(client):
    row = await _add(title="Belle villa")
    assert "Belle villa" in (await client.get("/")).text
    full = await client.get("/properties")
    assert "<html" in full.text and "Belle villa" in full.text
    assert "Pas de photo" in full.text
    htmx = await client.get("/properties?q=belle", headers={"HX-Request": "true"})
    assert "<html" not in htmx.text and "Belle villa" in htmx.text
    assert "Belle villa" in (await client.get(f"/properties/{row.id}")).text
    assert (await client.get("/runs")).status_code == 200


@pytest.mark.db
async def test_mandate_creation_flow(client):
    await _add(title="Match", city="Neuchâtel")
    await _add(title="Hors mandat", city="Genève")

    r = await client.post(
        "/mandates",
        data={
            "name": "NE only",
            "cities": "Neuchâtel",
            "max_price_chf": "1'000'000",
            "only_active": "on",
        },
    )
    assert r.status_code == 303
    page = await client.get(r.headers["location"])
    assert page.status_code == 200
    assert "Match" in page.text and "Hors mandat" not in page.text

    mandates = (await client.get("/api/mandates")).json()
    assert [m["name"] for m in mandates] == ["NE only"]
    matches = (await client.get(f"/api/mandates/{mandates[0]['id']}/matches")).json()
    assert matches["total"] == 1

    assert (await client.post("/mandates", data={"name": "  "})).status_code == 422
    created = await client.post("/api/mandates", json={"name": "API", "cities": ["Sion"]})
    assert created.status_code == 201


@pytest.mark.db
async def test_mandate_matches_unknown_id(client):
    r = await client.get("/api/mandates/00000000-0000-0000-0000-000000000000/matches")
    assert r.status_code == 404


@pytest.mark.db
async def test_guided_tour_hooks_are_present(client):
    """Les cibles du tour guidé (Driver.js) et le script doivent rester en place."""
    page = (await client.get("/properties")).text
    for hook in (
        'data-tour="sidebar"',
        'data-tour="search"',
        'data-tour="filters"',
        'data-tour="new-mandate"',
        'data-tour="nav-properties"',
        "/properties?tour=1",
    ):
        assert hook in page, hook
    assert "driver.js@1.3.1/dist/driver.js.iife.js" in page  # version épinglée
    assert page.index("driver.css") < page.index("style.css")  # notre thème doit l'emporter
    script = await client.get("/static/tour.js")
    assert script.status_code == 200 and "onDestroyStarted" in script.text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"price_status": "detail_page"}, "verified"),
        ({"price_status": "unverified_search_page"}, "estimated"),
        ({"price_status": "no_price_on_detail"}, None),
        ({}, None),
        (None, None),
    ],
)
def test_price_status_mapping(raw, expected):
    from immo_ne_collector.services.property_queries import price_status_of

    assert price_status_of(raw) == expected


@pytest.mark.db
async def test_price_status_visible_in_api_and_cards(client):
    await _add(title="Fiche lue", raw_data={"price_status": "detail_page"})
    await _add(title="Prix de liste", raw_data={"price_status": "unverified_search_page"})
    await _add(title="Autre source", raw_data={})
    items = {i["title"]: i for i in (await client.get("/api/properties")).json()["items"]}
    assert items["Fiche lue"]["price_status"] == "verified"
    assert items["Fiche lue"]["price_status_label"] == "Prix vérifié"
    assert items["Prix de liste"]["price_status"] == "estimated"
    assert items["Autre source"]["price_status"] is None
    page = (await client.get("/properties")).text
    assert (
        page.count("pstat-verified") == 1 and page.count("pstat-estimated") == 1
    )  # pas de badge sans info


@pytest.mark.db
async def test_settings_default_to_all_romandie_cantons(client):
    page = (await client.get("/settings")).text
    for canton in ("GE", "VD", "NE", "JU", "FR", "VS"):
        assert f'value="{canton}" checked' in page, canton


@pytest.mark.db
async def test_settings_page_has_html_upload_form():
    from httpx import ASGITransport, AsyncClient

    from immo_ne_collector.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        html = (await client.get("/settings")).text
        assert "Uploader une page HTML" in html and 'enctype="multipart/form-data"' in html
        bad = await client.post(
            "/settings/import",
            data={"source": "homegate", "canton": "all"},
            files={"html_file": ("x.html", b"   ", "text/html")},
        )
        assert bad.status_code == 422 and "vide" in bad.text


def test_database_unavailable_handler_explains_docker_host():
    import asyncio
    from types import SimpleNamespace

    from immo_ne_collector import main

    request = SimpleNamespace(url=SimpleNamespace(path="/api/stats"))
    original = main.settings.database_url
    main.settings.database_url = "postgresql+asyncpg://u:p@db:5432/immo_ne"
    try:
        resp = asyncio.run(main.database_unavailable(request, OSError("Name or service not known")))
    finally:
        main.settings.database_url = original
    assert resp.status_code == 503
    assert b"localhost" in resp.body and b"u:p" not in resp.body
