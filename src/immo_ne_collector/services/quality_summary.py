from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from immo_ne_collector.services.source_config import infer_detected_canton

QUALITY_SUMMARY_HEADERS = [
    "section",
    "dimension",
    "dimension_value",
    "count_issues",
    "count_properties",
    "percentage",
    "notes",
]


def _to_float_percent(value: float) -> str:
    return f"{value:.2f}"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as file_obj:
        return list(csv.DictReader(file_obj))


def count_master_properties(path: Path) -> int:
    rows = read_csv_rows(path)
    return len(rows)


def infer_sources_from_urls(raw_urls: str) -> set[str]:
    labels: set[str] = set()
    try:
        parsed = json.loads(raw_urls or "[]")
    except Exception:
        parsed = []
    if not isinstance(parsed, list):
        parsed = []

    for item in parsed:
        url = str(item or "")
        netloc = urlparse(url).netloc.lower()
        if "anibis.ch" in netloc:
            labels.add("anibis")
        elif "lookmove.ch" in netloc:
            labels.add("lookmove")
        elif "homegate.ch" in netloc:
            labels.add("homegate")
        elif "immoscout24.ch" in netloc or "immoscout.ch" in netloc:
            labels.add("immoscout")
    if not labels:
        labels.add("unknown")
    return labels


def infer_canton_from_row(row: dict[str, str]) -> str:
    city = row.get("city")
    postal_code = row.get("postal_code")
    try:
        urls = json.loads(row.get("source_urls") or "[]")
    except Exception:
        urls = []
    if not isinstance(urls, list):
        urls = []

    for url in urls:
        detected, _reason = infer_detected_canton(
            url=str(url or ""),
            city=city or None,
            postal_code=postal_code or None,
        )
        if detected != "unknown":
            return detected
    return "unknown"


def summarize_quality_rows(
    quality_rows: list[dict[str, str]],
    *,
    total_properties_in_master: int,
) -> list[dict[str, str]]:
    total_issues = len(quality_rows)
    property_ids = {row.get("property_id", "") for row in quality_rows if row.get("property_id")}
    properties_with_issues = len(property_ids)
    denominator = total_properties_in_master if total_properties_in_master > 0 else properties_with_issues
    pct_properties_with_issues = 0.0 if denominator == 0 else (properties_with_issues / denominator) * 100

    rows: list[dict[str, str]] = []

    def append_row(
        *,
        section: str,
        dimension: str,
        dimension_value: str,
        count_issues: int,
        count_properties: int,
        percentage: float,
        notes: str = "",
    ) -> None:
        rows.append(
            {
                "section": section,
                "dimension": dimension,
                "dimension_value": dimension_value,
                "count_issues": str(count_issues),
                "count_properties": str(count_properties),
                "percentage": _to_float_percent(percentage),
                "notes": notes,
            }
        )

    append_row(
        section="overview",
        dimension="total_issues",
        dimension_value="all",
        count_issues=total_issues,
        count_properties=properties_with_issues,
        percentage=100.0 if total_issues > 0 else 0.0,
        notes="Total lignes du quality_report.",
    )
    append_row(
        section="overview",
        dimension="total_properties_in_master",
        dimension_value="all",
        count_issues=0,
        count_properties=total_properties_in_master,
        percentage=100.0 if total_properties_in_master > 0 else 0.0,
        notes="Nombre de biens dans master.csv.",
    )
    append_row(
        section="overview",
        dimension="properties_with_issues",
        dimension_value="all",
        count_issues=total_issues,
        count_properties=properties_with_issues,
        percentage=pct_properties_with_issues,
        notes="Pourcentage des biens avec au moins une alerte.",
    )

    if total_issues == 0:
        return rows

    severity_counts = Counter((row.get("issue_severity") or "UNKNOWN").strip().upper() for row in quality_rows)
    severity_props: dict[str, set[str]] = defaultdict(set)
    for row in quality_rows:
        severity = (row.get("issue_severity") or "UNKNOWN").strip().upper()
        prop_id = row.get("property_id", "")
        if prop_id:
            severity_props[severity].add(prop_id)
    for severity, count in severity_counts.most_common():
        append_row(
            section="by_severity",
            dimension="issue_severity",
            dimension_value=severity,
            count_issues=count,
            count_properties=len(severity_props[severity]),
            percentage=(count / total_issues) * 100,
        )

    issue_counts = Counter((row.get("issue_code") or "UNKNOWN").strip().upper() for row in quality_rows)
    issue_props: dict[str, set[str]] = defaultdict(set)
    for row in quality_rows:
        code = (row.get("issue_code") or "UNKNOWN").strip().upper()
        prop_id = row.get("property_id", "")
        if prop_id:
            issue_props[code].add(prop_id)
    for code, count in issue_counts.most_common():
        append_row(
            section="by_issue_code",
            dimension="issue_code",
            dimension_value=code,
            count_issues=count,
            count_properties=len(issue_props[code]),
            percentage=(count / total_issues) * 100,
        )

    canton_counts: Counter[str] = Counter()
    canton_props: dict[str, set[str]] = defaultdict(set)
    source_counts: Counter[str] = Counter()
    source_props: dict[str, set[str]] = defaultdict(set)
    for row in quality_rows:
        prop_id = row.get("property_id", "")

        canton = infer_canton_from_row(row)
        canton_counts[canton] += 1
        if prop_id:
            canton_props[canton].add(prop_id)

        for source in infer_sources_from_urls(row.get("source_urls", "")):
            source_counts[source] += 1
            if prop_id:
                source_props[source].add(prop_id)

    for canton, count in canton_counts.most_common():
        append_row(
            section="by_canton",
            dimension="canton",
            dimension_value=canton,
            count_issues=count,
            count_properties=len(canton_props[canton]),
            percentage=(count / total_issues) * 100,
        )

    for source, count in source_counts.most_common():
        append_row(
            section="by_source",
            dimension="source",
            dimension_value=source,
            count_issues=count,
            count_properties=len(source_props[source]),
            percentage=(count / total_issues) * 100,
            notes="Issue comptée pour chaque source liée au bien.",
        )

    return rows


def write_quality_summary_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=QUALITY_SUMMARY_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
