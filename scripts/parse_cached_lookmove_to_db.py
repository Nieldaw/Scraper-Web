import argparse
import asyncio
import sys
from pathlib import Path

# ruff: noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.scrapers.lookmove import LookmoveCachedHtmlScraper, LookmoveParseError
from immo_ne_collector.services.anibis_filters import (
    VALID_CANTONS,
    VALID_TRANSACTION_TYPES,
    filter_collection_batch,
    resolve_canton,
)
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse un cache HTML Lookmove local et persiste les annonces en base.",
    )
    parser.add_argument("cache_file", type=Path, help="Chemin du fichier HTML cache Lookmove.")
    parser.add_argument(
        "--max-listings",
        type=int,
        default=None,
        help="Nombre max d'annonces à traiter après filtrage (ex: --max-listings 5).",
    )
    parser.add_argument(
        "--transaction-type",
        type=str,
        default="sale",
        choices=VALID_TRANSACTION_TYPES,
        help="Filtre de type de transaction: sale|rent|unknown|all (défaut: sale).",
    )
    parser.add_argument(
        "--canton",
        type=str,
        default="NE",
        choices=VALID_CANTONS,
        help="Filtre canton (MVP: NE).",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help="Alias simple de région (MVP: neuchatel).",
    )
    return parser


async def _run(
    file_path: Path,
    *,
    max_listings: int | None,
    transaction_type: str,
    canton: str | None,
) -> int:
    scraper = LookmoveCachedHtmlScraper(
        html_path=file_path,
        source="lookmove_cached",
    )
    try:
        batch = await collect_and_normalize(scraper)
    except LookmoveParseError as exc:
        print(f"Parse error: {exc}")
        return 1

    batch, stats = filter_collection_batch(
        batch,
        max_listings=max_listings,
        transaction_type=transaction_type,
        canton=canton,
    )
    result = await persist_collection_batch(batch)

    print(f"Cached HTML: {file_path}")
    print(f"Detected before filters: {stats.detected_total}")
    print(
        "Detected transaction types: "
        f"sale={stats.transaction_counts['sale']}, "
        f"rent={stats.transaction_counts['rent']}, "
        f"unknown={stats.transaction_counts['unknown']}"
    )
    print(f"Filter transaction_type: {transaction_type}")
    print(f"Filter canton: {canton if canton else 'none'}")
    if canton == "NE":
        print(f"Kept by canton NE: {stats.kept_canton_count}")
        print(f"Excluded out of canton: {stats.excluded_canton_count}")
        if stats.excluded_examples:
            print("Examples excluded:")
            for url in stats.excluded_examples:
                print(f"- {url}")
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
    try:
        canton = resolve_canton(canton=args.canton, region=args.region)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(2) from exc

    raise SystemExit(
        asyncio.run(
            _run(
                args.cache_file,
                max_listings=args.max_listings,
                transaction_type=args.transaction_type,
                canton=canton,
            )
        )
    )


if __name__ == "__main__":
    main()
