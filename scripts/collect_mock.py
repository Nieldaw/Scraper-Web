import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.scrapers.mock import MockScraper
from immo_ne_collector.services.collection import collect_and_normalize


async def _run() -> int:
    scraper = MockScraper()
    batch = await collect_and_normalize(scraper)

    print(f"Collected listings: {batch.collected_count}")
    print(f"Source: {batch.source}")
    print()

    for index, listing in enumerate(batch.listings, start=1):
        missing = ", ".join(listing.missing_fields) if listing.missing_fields else "none"
        print(f"{index}. title={listing.title or '<missing>'}")
        print(f"   price_chf={listing.price_chf}")
        print(f"   city={listing.city or '<missing>'}")
        print(f"   missing_fields={missing}")
        print()

    return batch.collected_count


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
