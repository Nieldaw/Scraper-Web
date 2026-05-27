from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from immo_ne_collector.scrapers.base import BaseScraper, RawListing


class AnibisParseError(RuntimeError):
    pass


class AnibisCachedHtmlScraper(BaseScraper):
    source = "anibis"

    def __init__(
        self,
        *,
        html_path: Path,
        source: str | None = None,
        base_url: str = "https://www.anibis.ch",
    ) -> None:
        self.html_path = Path(html_path)
        if source:
            self.source = source
        self.base_url = base_url
        super().__init__()

    async def collect(self) -> list[RawListing]:
        if not self.html_path.exists():
            raise AnibisParseError(f"Cached HTML file not found: {self.html_path}")
        html_text = self.html_path.read_text(encoding="utf-8")
        return self.parse_html(html_text)

    def parse_html(self, html_text: str) -> list[RawListing]:
        soup = BeautifulSoup(html_text, "html.parser")
        cards = soup.select("article.anibis-card[data-item-id]")
        if not cards:
            raise AnibisParseError(
                "No Anibis listing cards found. Expected selector: article.anibis-card[data-item-id]"
            )

        fetched_at = datetime.now(UTC)
        listings: list[RawListing] = []
        for idx, card in enumerate(cards, start=1):
            source_listing_id = card.get("data-item-id")
            link = card.select_one("a.anibis-link")
            href = link.get("href", "").strip() if link else ""
            if not source_listing_id or not href:
                raise AnibisParseError(f"Missing required id/url in card #{idx}")

            listings.append(
                RawListing(
                    source=self.source,
                    source_listing_id=source_listing_id,
                    url=urljoin(self.base_url, href),
                    title=self._text(card, ".anibis-title"),
                    property_type=self._text(card, ".anibis-type"),
                    price_raw=self._text(card, ".anibis-price"),
                    rooms_raw=self._text(card, ".anibis-rooms"),
                    living_area_raw=self._text(card, ".anibis-area"),
                    address_raw=self._text(card, ".anibis-address"),
                    city_raw=self._text(card, ".anibis-city"),
                    postal_code_raw=self._text(card, ".anibis-postal"),
                    description_raw=self._text(card, ".anibis-description"),
                    raw_data={
                        "fixture_or_cache_path": str(self.html_path),
                        "card_index": idx,
                        "parser": "anibis_cached_html",
                    },
                    fetched_at=fetched_at,
                )
            )

        return listings

    @staticmethod
    def _text(card, selector: str) -> str | None:
        node = card.select_one(selector)
        if node is None:
            return None
        cleaned = " ".join(node.get_text(" ", strip=True).split())
        return cleaned or None
