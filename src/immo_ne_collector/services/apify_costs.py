"""Synthèse des coûts Apify, lue dans la table ``apify_usage`` (alimentée par vos scripts)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from immo_ne_collector.models import ApifyUsage

LOCAL_TZ = ZoneInfo("Europe/Zurich")
FAILED_STATUSES = frozenset({"FAILED", "ABORTED", "ABORTING", "TIMED-OUT", "TIMED_OUT", "ERROR"})
ZERO = Decimal("0")


def month_start(now: datetime | None = None) -> datetime:
    """Début du mois courant (heure de Suisse), en UTC."""
    local = (now or datetime.now(UTC)).astimezone(LOCAL_TZ)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def _add_months(start: datetime, months: int) -> datetime:
    local = start.astimezone(LOCAL_TZ)
    index = local.year * 12 + (local.month - 1) + months
    return local.replace(year=index // 12, month=index % 12 + 1).astimezone(UTC)


@dataclass(frozen=True)
class MonthSummary:
    label: str  # « 05.2026 »
    total_cost: Decimal
    requests: int
    failed: int


@dataclass(frozen=True)
class ActorSummary:
    actor_id: str
    total_cost: Decimal
    requests: int


@dataclass(frozen=True)
class CostsOverview:
    current: MonthSummary
    by_actor: list[ActorSummary]
    history: list[MonthSummary]  # du plus récent au plus ancien, mois courant inclus
    recent: list[ApifyUsage]
    all_time_cost: Decimal
    all_time_requests: int


def _failed_count_expr():
    failed = case((func.upper(ApifyUsage.status).in_(FAILED_STATUSES), 1), else_=0)
    return func.coalesce(func.sum(failed), 0)


async def _month(session: AsyncSession, start: datetime, end: datetime) -> MonthSummary:
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(ApifyUsage.cost), 0),
                func.count(),
                _failed_count_expr(),
            ).where(ApifyUsage.date >= start, ApifyUsage.date < end)
        )
    ).one()
    return MonthSummary(
        label=start.astimezone(LOCAL_TZ).strftime("%m.%Y"),
        total_cost=Decimal(row[0]),
        requests=int(row[1]),
        failed=int(row[2]),
    )


async def load_costs_overview(
    session: AsyncSession, *, now: datetime | None = None, months: int = 6, recent: int = 15
) -> CostsOverview:
    now = now or datetime.now(UTC)
    start = month_start(now)
    end = _add_months(start, 1)
    current = await _month(session, start, end)

    history = [current]
    for back in range(1, months):
        lo, hi = _add_months(start, -back), _add_months(start, -back + 1)
        history.append(await _month(session, lo, hi))

    actors = (
        await session.execute(
            select(ApifyUsage.actor_id, func.coalesce(func.sum(ApifyUsage.cost), 0), func.count())
            .where(ApifyUsage.date >= start, ApifyUsage.date < end)
            .group_by(ApifyUsage.actor_id)
            .order_by(func.sum(ApifyUsage.cost).desc(), ApifyUsage.actor_id)
        )
    ).all()
    last = (
        (await session.execute(select(ApifyUsage).order_by(ApifyUsage.date.desc()).limit(recent)))
        .scalars()
        .all()
    )
    total = (
        await session.execute(select(func.coalesce(func.sum(ApifyUsage.cost), 0), func.count()))
    ).one()
    return CostsOverview(
        current=current,
        by_actor=[ActorSummary(a, Decimal(c), int(n)) for a, c, n in actors],
        history=history,
        recent=list(last),
        all_time_cost=Decimal(total[0]),
        all_time_requests=int(total[1]),
    )


def format_usd(value: Decimal | float | None) -> str:
    """Montant en dollars : 4 décimales sous 1 $ (« 0.0421 $ »), 2 au-delà (« 1'234.50 $ »)."""
    amount = Decimal(value or 0)
    digits = 4 if abs(amount) < 1 else 2
    return f"{amount:,.{digits}f}".replace(",", "'") + " $"
