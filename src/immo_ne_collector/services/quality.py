import csv
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from immo_ne_collector.models import Property

QUALITY_HEADERS = [
    "property_id",
    "title",
    "source_urls",
    "transaction_type",
    "city",
    "postal_code",
    "price_chf",
    "rooms",
    "living_area_m2",
    "issue_code",
    "issue_severity",
    "issue_message",
]


@dataclass(frozen=True)
class QualityThresholds:
    min_sale_price_chf: Decimal = Decimal("100000")
    max_sale_price_chf: Decimal = Decimal("10000000")
    min_area_m2: Decimal = Decimal("20")
    max_area_m2: Decimal = Decimal("1000")
    min_rooms: Decimal = Decimal("1")
    max_rooms: Decimal = Decimal("20")


DEFAULT_QUALITY_THRESHOLDS = QualityThresholds()


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class QualityExportResult:
    name: str
    path: Path
    row_count: int


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _to_text(value: object) -> str:
    return "" if value is None else str(value)


def _normalize_transaction_type(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in {"sale", "rent", "unknown"}:
        return cleaned
    return "unknown"


def _extract_transaction_types(property_row: Property) -> list[str]:
    values: list[str] = []
    for listing in property_row.listings:
        raw_value = None
        if isinstance(listing.raw_data, dict):
            raw_value = listing.raw_data.get("transaction_type")
        tx = _normalize_transaction_type(raw_value if isinstance(raw_value, str) else None)
        if tx not in values:
            values.append(tx)

    if values:
        return values

    fallback = None
    if isinstance(property_row.raw_data, dict):
        fallback = property_row.raw_data.get("transaction_type")
    return [_normalize_transaction_type(fallback if isinstance(fallback, str) else None)]


def _aggregate_transaction_type(transaction_types: list[str]) -> str:
    if not transaction_types:
        return "unknown"
    if len(transaction_types) == 1:
        return transaction_types[0]
    return "mixed"


def _source_urls(property_row: Property) -> list[str]:
    merged: list[str] = []
    for url in [*property_row.source_urls, *[item.url for item in property_row.listings if item.url]]:
        if url and url not in merged:
            merged.append(url)
    return merged


def _is_residential_type(property_type: str | None) -> bool:
    normalized = (property_type or "").strip().lower()
    return normalized in {"appartement", "maison"}


def _property_issues(
    property_row: Property,
    *,
    thresholds: QualityThresholds,
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    transaction_types = _extract_transaction_types(property_row)
    transaction_type = _aggregate_transaction_type(transaction_types)

    if transaction_type in {"unknown", "mixed"}:
        issues.append(
            QualityIssue(
                code="TRANSACTION_TYPE_UNKNOWN",
                severity="WARNING",
                message="Type de transaction inconnu ou mixte.",
            )
        )

    price_chf = _to_decimal(property_row.price_chf)
    rooms = _to_decimal(property_row.rooms)
    area = _to_decimal(property_row.living_area_m2)

    if transaction_type == "sale":
        if price_chf is None:
            issues.append(
                QualityIssue(
                    code="SALE_PRICE_MISSING",
                    severity="ERROR",
                    message="Prix absent pour une annonce de vente.",
                )
            )
        else:
            if price_chf < thresholds.min_sale_price_chf:
                issues.append(
                    QualityIssue(
                        code="SALE_PRICE_TOO_LOW",
                        severity="WARNING",
                        message="Prix de vente anormalement bas.",
                    )
                )
            if price_chf > thresholds.max_sale_price_chf:
                issues.append(
                    QualityIssue(
                        code="SALE_PRICE_TOO_HIGH",
                        severity="WARNING",
                        message="Prix de vente anormalement élevé.",
                    )
                )

    if _is_residential_type(property_row.property_type) and area is not None:
        if area < thresholds.min_area_m2:
            issues.append(
                QualityIssue(
                    code="AREA_TOO_LOW",
                    severity="WARNING",
                    message="Surface potentiellement incohérente (trop basse).",
                )
            )
        if area > thresholds.max_area_m2:
            issues.append(
                QualityIssue(
                    code="AREA_TOO_HIGH",
                    severity="WARNING",
                    message="Surface potentiellement incohérente (trop élevée).",
                )
            )

    if rooms is not None:
        if rooms < thresholds.min_rooms:
            issues.append(
                QualityIssue(
                    code="ROOMS_TOO_LOW",
                    severity="WARNING",
                    message="Nombre de pièces potentiellement incohérent (trop bas).",
                )
            )
        if rooms > thresholds.max_rooms:
            issues.append(
                QualityIssue(
                    code="ROOMS_TOO_HIGH",
                    severity="WARNING",
                    message="Nombre de pièces potentiellement incohérent (trop élevé).",
                )
            )

    if not property_row.city:
        issues.append(
            QualityIssue(
                code="CITY_MISSING",
                severity="WARNING",
                message="Commune manquante.",
            )
        )

    if not property_row.postal_code:
        issues.append(
            QualityIssue(
                code="POSTAL_CODE_MISSING",
                severity="WARNING",
                message="Code postal manquant.",
            )
        )

    if not property_row.address_full:
        issues.append(
            QualityIssue(
                code="ADDRESS_MISSING",
                severity="INFO",
                message="Adresse complète manquante.",
            )
        )

    completion_reason = (property_row.completion_reason or "").lower()
    sitn_status = (property_row.sitn_status or "").upper()
    if (
        property_row.sitn_eligible is False
        and (
            "adresse manquante" in completion_reason
            or sitn_status == "NOT_ELIGIBLE_MISSING_ADDRESS"
        )
    ):
        issues.append(
            QualityIssue(
                code="SITN_NOT_ELIGIBLE_ADDRESS",
                severity="INFO",
                message="SITN non éligible: adresse manquante/incomplète.",
            )
        )

    return issues


def _row_for_issue(property_row: Property, issue: QualityIssue) -> dict[str, str]:
    tx = _aggregate_transaction_type(_extract_transaction_types(property_row))
    return {
        "property_id": str(property_row.id),
        "title": _to_text(property_row.title),
        "source_urls": json.dumps(_source_urls(property_row), ensure_ascii=False),
        "transaction_type": tx,
        "city": _to_text(property_row.city),
        "postal_code": _to_text(property_row.postal_code),
        "price_chf": _to_text(property_row.price_chf),
        "rooms": _to_text(property_row.rooms),
        "living_area_m2": _to_text(property_row.living_area_m2),
        "issue_code": issue.code,
        "issue_severity": issue.severity,
        "issue_message": issue.message,
    }


def build_quality_rows(
    properties: list[Property],
    *,
    thresholds: QualityThresholds = DEFAULT_QUALITY_THRESHOLDS,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for property_row in properties:
        issues = _property_issues(property_row, thresholds=thresholds)
        rows.extend(_row_for_issue(property_row, issue) for issue in issues)
    return rows


async def export_quality_report_csv(
    session: AsyncSession,
    output_path: Path,
    *,
    thresholds: QualityThresholds = DEFAULT_QUALITY_THRESHOLDS,
    property_filter: Callable[[Property], bool] | None = None,
) -> QualityExportResult:
    query = select(Property).options(selectinload(Property.listings)).order_by(Property.first_seen_at.desc())
    properties = (await session.execute(query)).scalars().all()
    if property_filter is not None:
        properties = [row for row in properties if property_filter(row)]
    rows = build_quality_rows(properties, thresholds=thresholds)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=QUALITY_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    return QualityExportResult(name="QUALITY_REPORT", path=output_path, row_count=len(rows))
