from __future__ import annotations

import argparse
from pathlib import Path

# ruff: noqa: E402
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.services.quality_summary import (
    count_master_properties,
    read_csv_rows,
    summarize_quality_rows,
    write_quality_summary_csv,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Construit un resume synthese a partir de quality_report.csv sans recollecte reseau.",
    )
    parser.add_argument(
        "--quality-report",
        type=Path,
        default=ROOT / "data" / "exports" / "quality_report.csv",
        help="Chemin du quality_report.csv (defaut: data/exports/quality_report.csv).",
    )
    parser.add_argument(
        "--master-report",
        type=Path,
        default=ROOT / "data" / "exports" / "master.csv",
        help="Chemin du master.csv (defaut: data/exports/master.csv).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "exports" / "quality_summary.csv",
        help="Chemin du fichier de sortie (defaut: data/exports/quality_summary.csv).",
    )
    return parser


def run(quality_report: Path, master_report: Path, output: Path) -> int:
    quality_rows = read_csv_rows(quality_report)
    total_properties = count_master_properties(master_report)
    summary_rows = summarize_quality_rows(
        quality_rows,
        total_properties_in_master=total_properties,
    )
    write_quality_summary_csv(output, summary_rows)

    overview = {row["dimension"]: row for row in summary_rows if row.get("section") == "overview"}
    total_issues = overview.get("total_issues", {}).get("count_issues", "0")
    properties_with_issues = overview.get("properties_with_issues", {}).get("count_properties", "0")
    pct = overview.get("properties_with_issues", {}).get("percentage", "0.00")

    print(f"Quality report: {quality_report}")
    print(f"Master report: {master_report}")
    print(f"Summary output: {output}")
    print(f"Total issues: {total_issues}")
    print(f"Properties with issues: {properties_with_issues}")
    print(f"Properties with issues (%): {pct}")

    by_issue_code = [row for row in summary_rows if row.get("section") == "by_issue_code"]
    print("Top issue codes:")
    if by_issue_code:
        for row in by_issue_code[:5]:
            print(
                f"- {row['dimension_value']}: "
                f"{row['count_issues']} issues ({row['count_properties']} biens, {row['percentage']}%)"
            )
    else:
        print("- none")
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(run(args.quality_report, args.master_report, args.output))


if __name__ == "__main__":
    main()
