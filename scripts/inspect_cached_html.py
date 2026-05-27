from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


LISTING_LINK_RE = re.compile(r"^/[a-z]{2}/vi/[^\s]+/\d+(?:[/?#]|$)", flags=re.IGNORECASE)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


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

    return 0


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/inspect_cached_html.py data/cache/html/file.html")
        raise SystemExit(2)

    raise SystemExit(inspect_cached_html(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
