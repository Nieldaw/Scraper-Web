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

from immo_ne_collector.scrapers.homegate import HomegateCachedHtmlScraper, HomegateParseError
from immo_ne_collector.services.normalization import normalize_raw_listing
from immo_ne_collector.services.sitn import assess_sitn_eligibility


LISTING_LINK_RE = re.compile(r"/(?:acheter|buy)/", flags=re.IGNORECASE)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def inspect_cached_html(path: Path, *, base_url: str = "https://www.homegate.ch") -> int:
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    links = [a.get("href", "").strip() for a in soup.select("a[href]")]
    candidate_links = [href for href in links if LISTING_LINK_RE.search(href)]
    unique_candidates = list(dict.fromkeys(candidate_links))

    print(f"File: {path}")
    print(f"File size: {path.stat().st_size} bytes")
    print(f"Total links found: {len(links)}")
    print(
        f"Candidate listing links found: {len(candidate_links)} "
        f"({len(unique_candidates)} unique)"
    )

    if unique_candidates:
        print("Sample candidate links:")
        for href in unique_candidates[:12]:
            print(f"- {urljoin(base_url, href)}")

    candidate_cards = (
        soup.select("article[data-test='result-item']")
        or soup.select("article[data-testid='result-item']")
        or soup.select("div[data-test='result-item']")
        or soup.select("li[data-test='result-item']")
    )
    print(f"Candidate listing cards: {len(candidate_cards)}")

    if candidate_cards:
        print("Sample candidate titles:")
        for card in candidate_cards[:6]:
            title_node = card.select_one("h2") or card.select_one("h3")
            title = _clean_text(title_node.get_text(" ", strip=True)) if title_node else "(none)"
            print(f"- {title}")

    class_counts: Counter[str] = Counter()
    for node in soup.select("[class]"):
        for cls in node.get("class", []):
            class_counts[cls] += 1

    if class_counts:
        print("Most frequent classes:")
        for cls, count in class_counts.most_common(15):
            print(f"- {cls}: {count}")

    scraper = HomegateCachedHtmlScraper(html_path=path, source="homegate_inspect", base_url=base_url)
    try:
        raw_listings = scraper.parse_html(html)
    except HomegateParseError as exc:
        print(f"Parser quality diagnostic unavailable: {exc}")
        return 0

    normalized = [normalize_raw_listing(item) for item in raw_listings]
    transaction_counts = Counter(
        str(item.raw_data.get("transaction_type", "unknown")) for item in raw_listings
    )

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
    print(f"- sale: {transaction_counts.get('sale', 0)}")
    print(f"- rent: {transaction_counts.get('rent', 0)}")
    print(f"- unknown: {transaction_counts.get('unknown', 0)}")
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
        print("Usage: python3 scripts/inspect_homegate_cached_html.py data/cache/html/file.html")
        raise SystemExit(2)

    raise SystemExit(inspect_cached_html(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
