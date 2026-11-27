"""Page /costs : synthèse des coûts Apify (lecture seule de la table apify_usage)."""

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from immo_ne_collector.main import app
from immo_ne_collector.models import ApifyUsage
from immo_ne_collector.services import apify_costs
from immo_ne_collector.services.apify_costs import (
    ActorSummary,
    CostsOverview,
    MonthSummary,
    _add_months,
    format_usd,
    month_start,
)
from immo_ne_collector.web import routes


def test_month_start_utilise_le_fuseau_suisse():
    # 31 mai 23h30 UTC = 1er juin 01h30 à Zurich (été) : on est déjà en juin.
    start = month_start(datetime(2026, 5, 31, 23, 30, tzinfo=UTC))
    assert start == datetime(2026, 5, 31, 22, 0, tzinfo=UTC)
    assert month_start(datetime(2026, 1, 15, 12, 0, tzinfo=UTC)) == datetime(
        2025, 12, 31, 23, 0, tzinfo=UTC
    )


def test_add_months_traverse_les_annees():
    jan = month_start(datetime(2026, 1, 10, tzinfo=UTC))
    assert _add_months(jan, -1) == month_start(datetime(2025, 12, 10, tzinfo=UTC))
    assert _add_months(jan, 12) == month_start(datetime(2027, 1, 10, tzinfo=UTC))


def test_format_usd():
    assert format_usd(Decimal("0.0421")) == "0.0421 $"
    assert format_usd(Decimal("1234.5")) == "1'234.50 $"
    assert format_usd(None) == "0.0000 $"


def _overview(empty: bool) -> CostsOverview:
    cur = MonthSummary(
        "11.2026", Decimal("0" if empty else "3.5"), 0 if empty else 4, 0 if empty else 1
    )
    recent = (
        []
        if empty
        else [
            ApifyUsage(
                date=datetime(2026, 11, 3, 10, 0, tzinfo=UTC),
                actor_id="u/a",
                cost=Decimal("1.2"),
                status="SUCCEEDED",
            )
        ]
    )
    return CostsOverview(
        current=cur,
        by_actor=[] if empty else [ActorSummary("u/a", Decimal("3.5"), 4)],
        history=[cur],
        recent=recent,
        all_time_cost=Decimal("0" if empty else "9"),
        all_time_requests=0 if empty else 7,
    )


@pytest.mark.parametrize("empty", [True, False])
async def test_page_costs_rendue(monkeypatch, empty):
    async def fake(_session):
        return _overview(empty)

    monkeypatch.setattr(routes, "load_costs_overview", fake)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    resp = await client.get("/costs")
    assert resp.status_code == 200
    html = resp.text
    assert "Coûts Apify" in html and 'href="/costs"' in html
    if empty:
        assert "Aucun appel Apify enregistré" in html
    else:
        assert "3.50 $" in html and "Dépensé en 11.2026" in html
        assert "4</span><span>Requêtes ce mois-ci" in html
        assert "u/a" in html and "SUCCEEDED" in html


@pytest.mark.db
async def test_synthese_mois_en_base():
    from immo_ne_collector.db import AsyncSessionLocal

    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    rows = [
        ("u/a", "0.5", "SUCCEEDED", datetime(2026, 11, 2, 9, 0, tzinfo=UTC)),
        ("u/a", "0.25", "FAILED", datetime(2026, 11, 15, 9, 0, tzinfo=UTC)),
        ("u/b", "2", "SUCCEEDED", datetime(2026, 11, 18, 9, 0, tzinfo=UTC)),
        ("u/a", "10", "SUCCEEDED", datetime(2026, 10, 30, 9, 0, tzinfo=UTC)),  # mois précédent
    ]
    async with AsyncSessionLocal() as session:
        session.add_all(
            ApifyUsage(actor_id=a, cost=Decimal(c), status=st, date=d) for a, c, st, d in rows
        )
        await session.commit()
        ov = await apify_costs.load_costs_overview(session, now=now)
    assert ov.current.total_cost == Decimal("2.75")
    assert ov.current.requests == 3 and ov.current.failed == 1
    assert [(a.actor_id, a.total_cost) for a in ov.by_actor] == [
        ("u/b", Decimal("2")),
        ("u/a", Decimal("0.75")),
    ]
    assert ov.history[1].total_cost == Decimal("10") and ov.history[1].requests == 1
    assert ov.all_time_cost == Decimal("12.75") and ov.all_time_requests == 4
