import argparse
import asyncio
import sys
from pathlib import Path

# ruff: noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.scrapers.anibis import AnibisCachedHtmlScraper, AnibisParseError
from immo_ne_collector.services.collection import CollectionBatch
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch

VALID_TRANSACTION_TYPES = ("sale", "rent", "unknown", "all")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse un cache HTML Anibis local et persiste les annonces en base.",
    )
    parser.add_argument("cache_file", type=Path, help="Chemin du fichier HTML cache Anibis.")
    parser.add_argument(
        "--max-listings",
        type=int,
        default=None,
        help="Nombre max d'annonces à traiter après filtrage (ex: --max-listings 5).",
    )
    parser.add_argument(
        "--transaction-type",
        type=str,
        default="all",
        choices=VALID_TRANSACTION_TYPES,
        help="Filtre de type de transaction: sale|rent|unknown|all (défaut: all).",
    )
    return parser


def _filter_batch(
    batch: CollectionBatch,
    *,
    max_listings: int | None,
    transaction_type: str,
) -> tuple[CollectionBatch, int]:
    original_count = len(batch.listings)
    filtered = batch.listings
    if transaction_type != "all":
        filtered = [
            listing
            for listing in filtered
            if listing.raw_data.get("transaction_type", "unknown") == transaction_type
        ]

    if max_listings is not None:
        filtered = filtered[:max_listings]

    return (
        batch.model_copy(update={"listings": filtered, "collected_count": len(filtered)}),
        original_count,
    )


async def _run(
    file_path: Path,
    *,
    max_listings: int | None,
    transaction_type: str,
) -> int:
    scraper = AnibisCachedHtmlScraper(
        html_path=file_path,
        source="anibis_cached",
    )
    try:
        batch = await collect_and_normalize(scraper)
    except AnibisParseError as exc:
        print(f"Parse error: {exc}")
        return 1

    batch, raw_detected_count = _filter_batch(
        batch,
        max_listings=max_listings,
        transaction_type=transaction_type,
    )
    result = await persist_collection_batch(batch)
    print(f"Cached HTML: {file_path}")
    print(f"Detected before filters: {raw_detected_count}")
    print(f"Filter transaction_type: {transaction_type}")
    print(f"Filter max_listings: {max_listings if max_listings is not None else 'none'}")
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
    parser = _build_parser()
    args = parser.parse_args()
    if args.max_listings is not None and args.max_listings < 1:
        print("--max-listings must be >= 1")
        raise SystemExit(2)
    raise SystemExit(
        asyncio.run(
            _run(
                args.cache_file,
                max_listings=args.max_listings,
                transaction_type=args.transaction_type,
            )
        )
    )


if __name__ == "__main__":
    main()
