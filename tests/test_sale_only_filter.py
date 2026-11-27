"""Collecte « ventes uniquement » : les locations et offres indéterminées sont rejetées."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from immo_ne_collector.services.anibis_enrichment import enrich_anibis_batch
from immo_ne_collector.services.anibis_filters import (
    canonical_transaction_type,
    filter_collection_batch,
    is_strict_sale,
)
from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.normalization import NormalizedListing
from tests.test_anibis_detail_enrichment import _html


def _listing(idx: int, raw: dict) -> NormalizedListing:
    return NormalizedListing(
        source="anibis_cached",
        source_listing_id=f"id-{idx}",
        url=f"https://www.anibis.ch/fr/vi/neuchatel/immobilier/appartements/test/{idx}",
        title=f"Listing {idx}",
        property_type="appartement",
        price_chf=Decimal("900000"),
        rooms=Decimal("4.5"),
        living_area_m2=Decimal("100"),
        address_full="Rue du Seyon 12",
        city="Neuchâtel",
        postal_code="2000",
        description=None,
        raw_data=raw,
        fetched_at=datetime.now(UTC),
        missing_fields=[],
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("sale", "sale"), ("buy", "sale"), ("BUY", "sale"), (" Vente ", "sale"),
        ("rent", "rent"), ("location", "rent"), ("à louer", "unknown"),
        ("unknown", "unknown"), ("", "unknown"), (None, "unknown"), ("mixed", "unknown"),
    ],
)  # fmt: skip
def test_canonical_transaction_type(value, expected):
    assert canonical_transaction_type(value) == expected


def test_filtre_sale_rejette_locations_inconnus_et_absents():
    values = ["sale", "buy", "rent", "unknown", None, "mixed", "location"]
    listings = [
        _listing(i, {} if v is None else {"transaction_type": v}) for i, v in enumerate(values)
    ]
    batch = CollectionBatch(source="x", collected_count=len(listings), listings=listings)
    out, stats = filter_collection_batch(
        batch, max_listings=None, transaction_type="sale", canton=None
    )
    kept = [item.raw_data.get("transaction_type") for item in out.listings]
    assert kept == ["sale", "buy"]
    assert out.collected_count == 2
    assert stats.transaction_counts == {"sale": 2, "rent": 2, "unknown": 3}


def test_vente_avec_loyer_releve_sur_la_fiche_est_rejetee():
    assert is_strict_sale(_listing(1, {"transaction_type": "sale"}))
    assert not is_strict_sale(
        _listing(2, {"transaction_type": "sale", "detail_price_is_rent": True})
    )


async def test_enrichissement_ecarte_une_fiche_a_loyer_mensuel(tmp_path: Path):
    async def fetch(*, url, cache_dir, source, safety, rate_limiter):
        path = tmp_path / "rent.html"
        path.write_text(_html("rent"), encoding="utf-8")
        return SimpleNamespace(file_path=path, status_code=200)

    batch = CollectionBatch(
        source="anibis_cached",
        collected_count=1,
        listings=[_listing(1, {"transaction_type": "sale"})],
    )
    out, report = await enrich_anibis_batch(
        batch, delay_seconds=0, cache_dir=tmp_path / "cache", fetch=fetch
    )
    assert out.listings == [] and out.collected_count == 0
    assert report.excluded_rent == 1 and any("loyer" in w for w in report.warnings)


def test_modele_apify_usage_colonnes():
    from immo_ne_collector.models import ApifyUsage

    cols = {c.name for c in ApifyUsage.__table__.columns}
    assert cols == {"id", "date", "actor_id", "cost", "status"}
    assert ApifyUsage.__tablename__ == "apify_usage"


@pytest.mark.db
async def test_apify_usage_enregistre_et_additionne_les_couts():
    from decimal import Decimal as D

    from sqlalchemy import func, select

    from immo_ne_collector.db import AsyncSessionLocal
    from immo_ne_collector.models import ApifyUsage

    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                ApifyUsage(actor_id="user/actor-a", cost=D("0.0421"), status="SUCCEEDED"),
                ApifyUsage(actor_id="user/actor-a", cost=D("0.5"), status="FAILED"),
            ]
        )
        await session.commit()
        total = (await session.execute(select(func.sum(ApifyUsage.cost)))).scalar_one()
        row = (await session.execute(select(ApifyUsage).limit(1))).scalar_one_or_none()
        assert total == D("0.5421")
        assert row is not None and row.date is not None and row.id is not None
