from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# ruff: noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from immo_ne_collector.scrapers.immoscout import (
    ImmoscoutCachedHtmlScraper,
    ImmoscoutParseError,
    detect_immoscout_challenge_html,
)
from immo_ne_collector.services.normalization import normalize_raw_listing
from immo_ne_collector.services.sitn import assess_sitn_eligibility


LISTING_LINK_RE = re.compile(r"/(?:acheter|buy|listing|annonce)/", flags=re.IGNORECASE)


def inspect_cached_html(path: Path, *, base_url: str = "https://www.immoscout24.ch") -> int:
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    html = path.read_text(encoding="utf-8")
    challenge_detected, challenge_reason = detect_immoscout_challenge_html(html)
    soup = BeautifulSoup(html, "html.parser")

    links = [a.get("href", "").strip() for a in soup.select("a[href]")]
    candidate_links = [href for href in links if LISTING_LINK_RE.search(href)]
    unique_candidates = list(dict.fromkeys(candidate_links))

    print(f"File: {path}")
    print(f"File size: {path.stat().st_size} bytes")
    print(f"Challenge detected: {challenge_detected}")
    if challenge_reason:
        print(f"Challenge reason: {challenge_reason}")
    print(f"Total links found: {len(links)}")
    print(
        f"Candidate listing links found: {len(candidate_links)} "
        f"({len(unique_candidates)} unique)"
    )
    if unique_candidates:
        print("Sample candidate links:")
        for href in unique_candidates[:12]:
            print(f"- {urljoin(base_url, href)}")

    cards = (
        soup.select("article[data-listing-id]")
        or soup.select("article[data-testid='result-list-item']")
        or soup.select("article[data-test='result-item']")
        or soup.select("div[data-listing-id]")
        or soup.select("li[data-listing-id]")
    )
    print(f"Candidate listing cards: {len(cards)}")

    class_counts: Counter[str] = Counter()
    for node in soup.select("[class]"):
        for cls in node.get("class", []):
            class_counts[cls] += 1
    if class_counts:
        print("Most frequent classes:")
        for cls, count in class_counts.most_common(15):
            print(f"- {cls}: {count}")

    scraper = ImmoscoutCachedHtmlScraper(
        html_path=path,
        source="immoscout_inspect",
        base_url=base_url,
    )
    try:
        raw_listings = scraper.parse_html(html)
    except ImmoscoutParseError as exc:
        print(f"Parser quality diagnostic unavailable: {exc}")
        return 0

    normalized = [normalize_raw_listing(item) for item in raw_listings]
    tx_counts = Counter(str(item.raw_data.get("transaction_type", "unknown")) for item in raw_listings)
    parser_strategy_counts = Counter(str(item.raw_data.get("parser_strategy", "unknown")) for item in raw_listings)

    with_price = sum(1 for item in normalized if item.price_chf is not None)
    with_rooms = sum(1 for item in normalized if item.rooms is not None)
    with_area = sum(1 for item in normalized if item.living_area_m2 is not None)
    with_city = sum(1 for item in normalized if item.city is not None)
    with_postal = sum(1 for item in normalized if item.postal_code is not None)
    with_address = sum(1 for item in normalized if item.address_full is not None)
    sitn_eligible_count = sum(
        1 for item in normalized if assess_sitn_eligibility(item.address_full, item.city).eligible
    )

    print("Quality diagnostics:")
    print(f"- Total listings detected: {len(raw_listings)}")
    print(f"- sale: {tx_counts.get('sale', 0)}")
    print(f"- rent: {tx_counts.get('rent', 0)}")
    print(f"- unknown: {tx_counts.get('unknown', 0)}")
    print(f"- parser strategies: {dict(parser_strategy_counts)}")
    print(f"- with price: {with_price}")
    print(f"- with rooms: {with_rooms}")
    print(f"- with area: {with_area}")
    print(f"- with city: {with_city}")
    print(f"- with postal code: {with_postal}")
    print(f"- with address: {with_address}")
    print(f"- SITN eligible: {sitn_eligible_count}")
    return 0


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/inspect_immoscout_cached_html.py data/cache/html/file.html")
        raise SystemExit(2)
    raise SystemExit(inspect_cached_html(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
