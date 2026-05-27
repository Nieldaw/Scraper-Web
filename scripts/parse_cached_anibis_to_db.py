import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.scrapers.anibis import AnibisCachedHtmlScraper, AnibisParseError
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch


async def _run(file_path: Path) -> int:
    scraper = AnibisCachedHtmlScraper(
        html_path=file_path,
        source="anibis_cached",
    )
    try:
        batch = await collect_and_normalize(scraper)
    except AnibisParseError as exc:
        print(f"Parse error: {exc}")
        return 1

    result = await persist_collection_batch(batch)
    print(f"Cached HTML: {file_path}")
    print(f"DailyRun ID: {result.daily_run_id}")
    print(f"Collected: {result.collected_count}")
    print(f"Created: {result.created_count}")
    print(f"Updated: {result.updated_count}")
    print(f"Unchanged: {result.unchanged_count}")
    print(f"Errors: {len(result.errors)}")
    if result.errors:
        for err in result.errors:
            print(f"- {err}")
        return 1
    return 0


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/parse_cached_anibis_to_db.py data/cache/html/file.html")
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_run(Path(sys.argv[1]))))


if __name__ == "__main__":
    main()
