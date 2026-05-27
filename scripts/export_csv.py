import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.services.exports import export_all_csv


async def _run() -> int:
    results = await export_all_csv(output_dir=ROOT / "data" / "exports")
    print("CSV exports generated:")
    for result in results:
        print(f"- {result.name}: {result.path} ({result.row_count} rows)")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
