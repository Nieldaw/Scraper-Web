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

from immo_ne_collector.scrapers.anibis import AnibisCachedHtmlScraper, AnibisParseError
from immo_ne_collector.scrapers.anibis_utils import is_canton_ne_listing
from immo_ne_collector.services.normalization import normalize_raw_listing
from immo_ne_collector.services.sitn import assess_sitn_eligibility


LISTING_LINK_RE = re.compile(r"^/[a-z]{2}/vi/[^\s]+/\d+(?:[/?#]|$)", flags=re.IGNORECASE)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _is_complete_address(address_full: str | None) -> bool:
    if not address_full:
        return False
    has_number = re.search(r"\b\d+[a-zA-Z]?\b", address_full) is not None
    has_street_text = re.search(r"[A-Za-z]{3,}", address_full) is not None
    return has_number and has_street_text


def inspect_cached_html(path: Path, *, base_url: str = "https://www.anibis.ch") -> int:
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    links = [a.get("href", "").strip() for a in soup.select("a[href]")]
    candidate_links = [href for href in links if LISTING_LINK_RE.match(href)]
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

    fixture_cards = soup.select("article.anibis-card[data-item-id]")
    real_cards = soup.select("div[data-private-srp-listing-item-id]")

    print(f"Fixture-style cards: {len(fixture_cards)}")
    print(f"Real SRP cards: {len(real_cards)}")

    cards = real_cards or fixture_cards
    if not cards:
        print(
            "No listing blocks found. Tried selectors: "
            "article.anibis-card[data-item-id], div[data-private-srp-listing-item-id]."
        )
    else:
        print("Sample listing titles:")
        for card in cards[:6]:
            title_node = card.select_one("h2") or card.select_one(".anibis-title")
            title = _clean_text(title_node.get_text(" ", strip=True)) if title_node else "(none)"
            print(f"- {title}")

        data_attr_counts: Counter[str] = Counter()
        for card in cards:
            for key in card.attrs:
                if key.startswith("data-"):
                    data_attr_counts[key] += 1

        if data_attr_counts:
            print("Data attributes on listing blocks:")
            for key, count in data_attr_counts.most_common(8):
                print(f"- {key}: {count}")

    class_counts: Counter[str] = Counter()
    for node in soup.select("[class]"):
        for cls in node.get("class", []):
            class_counts[cls] += 1

    if class_counts:
        print("Most frequent classes:")
        for cls, count in class_counts.most_common(15):
            print(f"- {cls}: {count}")

    scraper = AnibisCachedHtmlScraper(html_path=path, source="anibis_inspect", base_url=base_url)
    try:
        raw_listings = scraper.parse_html(html)
    except AnibisParseError as exc:
        print(f"Parser quality diagnostic unavailable: {exc}")
        return 0

    normalized = [normalize_raw_listing(item) for item in raw_listings]
    transaction_counts = Counter(
        str(item.raw_data.get("transaction_type", "unknown")) for item in raw_listings
    )
    with_price = sum(1 for item in normalized if item.price_chf is not None)
    with_surface = sum(1 for item in normalized if item.living_area_m2 is not None)
    with_rooms = sum(1 for item in normalized if item.rooms is not None)
    with_city = sum(1 for item in normalized if item.city is not None)
    with_postal = sum(1 for item in normalized if item.postal_code is not None)
    with_complete_address = sum(1 for item in normalized if _is_complete_address(item.address_full))
    sitn_eligible_count = sum(
        1 for item in normalized if assess_sitn_eligibility(item.address_full, item.city).eligible
    )
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
    print(f"- with price: {with_price}")
    print(f"- with surface: {with_surface}")
    print(f"- with rooms: {with_rooms}")
    print(f"- with city: {with_city}")
    print(f"- with postal code: {with_postal}")
    print(f"- with complete address: {with_complete_address}")
    print(f"- SITN eligible: {sitn_eligible_count}")
    print(f"- kept by canton NE: {len(kept_canton_ne)}")
    print(f"- excluded out of canton: {len(excluded_canton_ne)}")
    if excluded_canton_ne:
        print("- examples excluded:")
        for listing in excluded_canton_ne[:5]:
            print(f"  - {listing.url}")

    return 0


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/inspect_cached_html.py data/cache/html/file.html")
        raise SystemExit(2)

    raise SystemExit(inspect_cached_html(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
