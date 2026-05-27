import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.services.exports import export_all_csv
from immo_ne_collector.services.quality import export_quality_report_csv


async def _run() -> int:
    output_dir = ROOT / "data" / "exports"
    results = await export_all_csv(output_dir=output_dir)
    try:
        from immo_ne_collector.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            quality_result = await export_quality_report_csv(
                session,
                output_dir / "quality_report.csv",
            )
        results.append(quality_result)
    except Exception as exc:  # pragma: no cover - defensive non-blocking path
        print(f"Warning: quality report generation failed: {exc}")

    print("CSV exports generated:")
    for result in results:
        print(f"- {result.name}: {result.path} ({result.row_count} rows)")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
