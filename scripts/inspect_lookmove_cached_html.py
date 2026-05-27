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

from immo_ne_collector.scrapers.anibis_utils import is_canton_ne_listing
from immo_ne_collector.scrapers.lookmove import LookmoveCachedHtmlScraper, LookmoveParseError
from immo_ne_collector.services.normalization import normalize_raw_listing
from immo_ne_collector.services.sitn import assess_sitn_eligibility


LISTING_LINK_RE = re.compile(r"/(?:annonce|listing)/", flags=re.IGNORECASE)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _is_complete_address(address_full: str | None) -> bool:
    if not address_full:
        return False
    has_number = re.search(r"\b\d+[a-zA-Z]?\b", address_full) is not None
    has_street_text = re.search(r"[A-Za-z]{3,}", address_full) is not None
    return has_number and has_street_text


def inspect_cached_html(path: Path, *, base_url: str = "https://www.lookmove.ch") -> int:
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
        soup.select("article.lookmove-card[data-listing-id]")
        or soup.select("article[data-listing-id]")
        or soup.select("div[data-listing-id]")
    )
    print(f"Candidate listing cards: {len(candidate_cards)}")

    if candidate_cards:
        print("Sample candidate titles:")
        for card in candidate_cards[:6]:
            title_node = card.select_one("h2") or card.select_one("h3")
            title = _clean_text(title_node.get_text(" ", strip=True)) if title_node else "(none)"
            print(f"- {title}")

        data_attr_counts: Counter[str] = Counter()
        for card in candidate_cards:
            for key in card.attrs:
                if key.startswith("data-"):
                    data_attr_counts[key] += 1

        if data_attr_counts:
            print("Data attributes on listing blocks:")
            for key, count in data_attr_counts.most_common(10):
                print(f"- {key}: {count}")

    class_counts: Counter[str] = Counter()
    for node in soup.select("[class]"):
        for cls in node.get("class", []):
            class_counts[cls] += 1

    if class_counts:
        print("Most frequent classes:")
        for cls, count in class_counts.most_common(15):
            print(f"- {cls}: {count}")

    scraper = LookmoveCachedHtmlScraper(html_path=path, source="lookmove_inspect", base_url=base_url)
    try:
        raw_listings = scraper.parse_html(html)
    except LookmoveParseError as exc:
        print(f"Parser quality diagnostic unavailable: {exc}")
        return 0

    normalized = [normalize_raw_listing(item) for item in raw_listings]
    transaction_counts = Counter(
        str(item.raw_data.get("transaction_type", "unknown")) for item in raw_listings
    )
    detected_titles = [str(item.raw_data.get("detected_title")) for item in raw_listings if item.raw_data.get("detected_title")]
    detected_cities = [str(item.raw_data.get("detected_city")) for item in raw_listings if item.raw_data.get("detected_city")]
    detected_prices = [str(item.raw_data.get("detected_price_text")) for item in raw_listings if item.raw_data.get("detected_price_text")]
    rejected_price_reasons = Counter(
        str(item.raw_data.get("rejected_price_reason"))
        for item in raw_listings
        if item.raw_data.get("rejected_price_reason")
    )

    with_city = sum(1 for item in normalized if item.city is not None)
    with_postal = sum(1 for item in normalized if item.postal_code is not None)
    with_complete_address = sum(1 for item in normalized if _is_complete_address(item.address_full))
    kept_canton_ne = []
    excluded_canton_ne = []
    for item in normalized:
        if is_canton_ne_listing(item.url, item.city, item.postal_code):
            kept_canton_ne.append(item)
        else:
            excluded_canton_ne.append(item)

    print("Quality diagnostics:")
    print(f"- Total listings detected: {len(raw_listings)}")
    print(f"- sale: {transaction_counts.get('sale', 0)}")
    print(f"- rent: {transaction_counts.get('rent', 0)}")
    print(f"- unknown: {transaction_counts.get('unknown', 0)}")
    print(f"- with city: {with_city}")
    print(f"- with postal code: {with_postal}")
    print(f"- with complete address: {with_complete_address}")
    sitn_eligible_count = sum(
        1 for item in normalized if assess_sitn_eligibility(item.address_full, item.city).eligible
    )
    print(f"- SITN eligible: {sitn_eligible_count}")
    print(f"- kept by canton NE: {len(kept_canton_ne)}")
    print(f"- excluded out of canton: {len(excluded_canton_ne)}")
    if excluded_canton_ne:
        print("- examples excluded:")
        for listing in excluded_canton_ne[:5]:
            print(f"  - {listing.url}")
    if detected_titles:
        print("- candidate titles:")
        for title in detected_titles[:8]:
            print(f"  - {title}")
    if detected_cities:
        print("- candidate cities:")
        for city in detected_cities[:8]:
            print(f"  - {city}")
    if detected_prices:
        print("- candidate prices:")
        for price in detected_prices[:8]:
            print(f"  - {price}")
    if rejected_price_reasons:
        print("- rejected price reasons:")
        for reason, count in rejected_price_reasons.most_common():
            print(f"  - {reason}: {count}")

    return 0


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/inspect_lookmove_cached_html.py data/cache/html/file.html")
        raise SystemExit(2)

    raise SystemExit(inspect_cached_html(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
