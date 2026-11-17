from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

from immo_ne_collector.services.quality_summary import (
    build_quality_summary_markdown,
    QUALITY_SUMMARY_HEADERS,
    count_master_properties,
    read_csv_rows,
    summarize_quality_rows,
    write_quality_summary_csv,
    write_quality_summary_markdown,
)


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "summarize_quality_report.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("summarize_quality_report", SCRIPT_PATH)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
SCRIPT_MODULE = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(SCRIPT_MODULE)


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def test_quality_summary_basic(tmp_path: Path) -> None:
    quality_path = tmp_path / "quality_report.csv"
    master_path = tmp_path / "master.csv"
    output_path = tmp_path / "quality_summary.csv"

    _write_csv(
        quality_path,
        [
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
        ],
        [
            {
                "property_id": "p1",
                "title": "T1",
                "source_urls": '["https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans-neuchatel/1"]',
                "transaction_type": "sale",
                "city": "Neuchatel",
                "postal_code": "2000",
                "price_chf": "500000.00",
                "rooms": "4.0",
                "living_area_m2": "90.0",
                "issue_code": "CITY_MISSING",
                "issue_severity": "WARNING",
                "issue_message": "x",
            },
            {
                "property_id": "p1",
                "title": "T1",
                "source_urls": '["https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans-neuchatel/1"]',
                "transaction_type": "sale",
                "city": "Neuchatel",
                "postal_code": "2000",
                "price_chf": "500000.00",
                "rooms": "4.0",
                "living_area_m2": "90.0",
                "issue_code": "POSTAL_CODE_MISSING",
                "issue_severity": "WARNING",
                "issue_message": "x",
            },
            {
                "property_id": "p2",
                "title": "T2",
                "source_urls": '["https://www.anibis.ch/fr/vi/vaud/immobilier/appartements/2"]',
                "transaction_type": "sale",
                "city": "Lausanne",
                "postal_code": "1000",
                "price_chf": "750000.00",
                "rooms": "5.0",
                "living_area_m2": "120.0",
                "issue_code": "SALE_PRICE_MISSING",
                "issue_severity": "ERROR",
                "issue_message": "x",
            },
        ],
    )
    _write_csv(
        master_path,
        ["property_id", "title"],
        [
            {"property_id": "p1", "title": "T1"},
            {"property_id": "p2", "title": "T2"},
            {"property_id": "p3", "title": "T3"},
        ],
    )

    quality_rows = read_csv_rows(quality_path)
    total_properties = count_master_properties(master_path)
    summary_rows = summarize_quality_rows(quality_rows, total_properties_in_master=total_properties)
    write_quality_summary_csv(output_path, summary_rows)
    write_quality_summary_markdown(tmp_path / "quality_summary.md", summary_rows)

    written = read_csv_rows(output_path)
    assert written
    assert set(written[0].keys()) == set(QUALITY_SUMMARY_HEADERS)

    by_overview = {row["dimension"]: row for row in written if row["section"] == "overview"}
    assert by_overview["total_issues"]["count_issues"] == "3"
    assert by_overview["properties_with_issues"]["count_properties"] == "2"
    assert by_overview["properties_with_issues"]["percentage"] == "66.67"

    by_source = [row for row in written if row["section"] == "by_source"]
    by_source_map = {row["dimension_value"]: row for row in by_source}
    assert by_source_map["lookmove"]["count_issues"] == "2"
    assert by_source_map["anibis"]["count_issues"] == "1"

    by_canton = [row for row in written if row["section"] == "by_canton"]
    by_canton_map = {row["dimension_value"]: row for row in by_canton}
    assert by_canton_map["NE"]["count_issues"] == "2"
    assert by_canton_map["VD"]["count_issues"] == "1"

    markdown = (tmp_path / "quality_summary.md").read_text(encoding="utf-8")
    assert "# Resume qualite" in markdown
    assert "Top issue codes:" in markdown
    assert "By issue code" in markdown
    assert build_quality_summary_markdown(summary_rows) == markdown


def test_quality_summary_handles_empty_quality_report(tmp_path: Path) -> None:
    quality_path = tmp_path / "quality_report.csv"
    master_path = tmp_path / "master.csv"
    output_path = tmp_path / "quality_summary.csv"

    _write_csv(
        quality_path,
        [
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
        ],
        [],
    )
    _write_csv(
        master_path,
        ["property_id", "title"],
        [{"property_id": "p1", "title": "T1"}],
    )

    summary_rows = summarize_quality_rows(
        read_csv_rows(quality_path),
        total_properties_in_master=count_master_properties(master_path),
    )
    write_quality_summary_csv(output_path, summary_rows)
    write_quality_summary_markdown(tmp_path / "quality_summary.md", summary_rows)

    written = read_csv_rows(output_path)
    assert written
    assert len(written) == 3
    by_overview = {row["dimension"]: row for row in written if row["section"] == "overview"}
    assert by_overview["total_issues"]["count_issues"] == "0"
    assert by_overview["properties_with_issues"]["count_properties"] == "0"
    assert by_overview["properties_with_issues"]["percentage"] == "0.00"

    markdown = (tmp_path / "quality_summary.md").read_text(encoding="utf-8")
    assert "Total issues: 0" in markdown
    assert "_No quality issues found in quality_report.csv._" in markdown


def test_quality_summary_orders_top_issue_codes_and_groups_dimensions(tmp_path: Path) -> None:
    quality_path = tmp_path / "quality_report.csv"
    master_path = tmp_path / "master.csv"
    output_path = tmp_path / "quality_summary.csv"
    markdown_path = tmp_path / "quality_summary.md"

    _write_csv(
        quality_path,
        [
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
        ],
        [
            {
                "property_id": "p1",
                "title": "T1",
                "source_urls": '["https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans-neuchatel/1"]',
                "transaction_type": "sale",
                "city": "Neuchatel",
                "postal_code": "2000",
                "price_chf": "500000.00",
                "rooms": "4.0",
                "living_area_m2": "90.0",
                "issue_code": "CITY_MISSING",
                "issue_severity": "WARNING",
                "issue_message": "x",
            },
            {
                "property_id": "p2",
                "title": "T2",
                "source_urls": '["https://www.anibis.ch/fr/vi/vaud/immobilier/appartements/2"]',
                "transaction_type": "sale",
                "city": "Lausanne",
                "postal_code": "1000",
                "price_chf": "750000.00",
                "rooms": "5.0",
                "living_area_m2": "120.0",
                "issue_code": "ADDRESS_MISSING",
                "issue_severity": "INFO",
                "issue_message": "x",
            },
            {
                "property_id": "p3",
                "title": "T3",
                "source_urls": '["https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans/delemont/3"]',
                "transaction_type": "sale",
                "city": "Delémont",
                "postal_code": "2800",
                "price_chf": "250000.00",
                "rooms": "3.0",
                "living_area_m2": "60.0",
                "issue_code": "ADDRESS_MISSING",
                "issue_severity": "INFO",
                "issue_message": "x",
            },
            {
                "property_id": "p4",
                "title": "T4",
                "source_urls": '["https://www.anibis.ch/fr/vi/neuchatel/immobilier/appartements/4", "https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans/neuchatel/4"]',
                "transaction_type": "sale",
                "city": "Neuchatel",
                "postal_code": "2000",
                "price_chf": "390000.00",
                "rooms": "3.5",
                "living_area_m2": "80.0",
                "issue_code": "POSTAL_CODE_MISSING",
                "issue_severity": "WARNING",
                "issue_message": "x",
            },
        ],
    )
    _write_csv(
        master_path,
        ["property_id", "title"],
        [
            {"property_id": "p1", "title": "T1"},
            {"property_id": "p2", "title": "T2"},
            {"property_id": "p3", "title": "T3"},
            {"property_id": "p4", "title": "T4"},
        ],
    )

    summary_rows = summarize_quality_rows(
        read_csv_rows(quality_path),
        total_properties_in_master=count_master_properties(master_path),
    )
    write_quality_summary_csv(output_path, summary_rows)
    write_quality_summary_markdown(markdown_path, summary_rows)

    by_issue_code = [row for row in summary_rows if row["section"] == "by_issue_code"]
    assert by_issue_code[0]["dimension_value"] == "ADDRESS_MISSING"
    assert by_issue_code[0]["count_issues"] == "2"

    by_source = {row["dimension_value"]: row for row in summary_rows if row["section"] == "by_source"}
    assert by_source["lookmove"]["count_issues"] == "3"
    assert by_source["anibis"]["count_issues"] == "2"

    by_canton = {row["dimension_value"]: row for row in summary_rows if row["section"] == "by_canton"}
    assert by_canton["NE"]["count_issues"] == "2"
    assert by_canton["VD"]["count_issues"] == "1"
    assert by_canton["JU"]["count_issues"] == "1"

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "ADDRESS_MISSING (2)" in markdown
    assert "## By source" in markdown


def test_summarize_quality_report_script_writes_csv_and_md(tmp_path: Path) -> None:
    quality_path = tmp_path / "quality_report.csv"
    master_path = tmp_path / "master.csv"
    csv_output = tmp_path / "quality_summary.csv"
    md_output = tmp_path / "quality_summary.md"

    _write_csv(
        quality_path,
        [
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
        ],
        [
            {
                "property_id": "p1",
                "title": "T1",
                "source_urls": '["https://www.lookmove.ch/fr/annonce/acheter/a-vendre-appartement-dans-neuchatel/1"]',
                "transaction_type": "sale",
                "city": "Neuchatel",
                "postal_code": "2000",
                "price_chf": "500000.00",
                "rooms": "4.0",
                "living_area_m2": "90.0",
                "issue_code": "CITY_MISSING",
                "issue_severity": "WARNING",
                "issue_message": "x",
            }
        ],
    )
    _write_csv(
        master_path,
        ["property_id", "title"],
        [{"property_id": "p1", "title": "T1"}],
    )

    exit_code = SCRIPT_MODULE.run(quality_path, master_path, csv_output, md_output)
    assert exit_code == 0
    assert csv_output.exists()
    assert md_output.exists()

    csv_rows = read_csv_rows(csv_output)
    by_issue_code = {row["dimension_value"]: row for row in csv_rows if row["section"] == "by_issue_code"}
    assert by_issue_code["CITY_MISSING"]["count_issues"] == "1"
    assert "CITY_MISSING" in md_output.read_text(encoding="utf-8")
