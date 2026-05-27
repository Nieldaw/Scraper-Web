import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.scrapers.mock import MockScraper
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch


async def _run() -> int:
    batch = await collect_and_normalize(MockScraper())
    result = await persist_collection_batch(batch)

    print(f"DailyRun ID: {result.daily_run_id}")
    print(f"Collected: {result.collected_count}")
    print(f"Created: {result.created_count}")
    print(f"Updated: {result.updated_count}")
    print(f"Unchanged: {result.unchanged_count}")
    print(f"Errors: {len(result.errors)}")

    if result.errors:
        print()
        print("Error details:")
        for err in result.errors:
            print(f"- {err}")
        return 1

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
