from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from immo_ne_collector.scrapers.base import BaseScraper, RawListing


class StaticHtmlScraper(BaseScraper):
    source = "static_html"

    def __init__(
        self,
        *,
        html_path: Path,
        source: str | None = None,
        base_url: str = "https://static.example",
    ) -> None:
        self.html_path = Path(html_path)
        if source:
            self.source = source
        self.base_url = base_url
        super().__init__()

    async def collect(self) -> list[RawListing]:
        html_text = self.html_path.read_text(encoding="utf-8")
        return self.parse_html(html_text)

    def parse_html(self, html_text: str) -> list[RawListing]:
        soup = BeautifulSoup(html_text, "html.parser")
        cards = soup.select("article.listing-card[data-listing-id]")
        fetched_at = datetime.now(UTC)
        listings: list[RawListing] = []

        for index, card in enumerate(cards, start=1):
            source_listing_id = card.get("data-listing-id")
            link = card.select_one("a.listing-link")
            href = link.get("href", "").strip() if link else ""
            url = urljoin(self.base_url, href)

            title = self._text(card, ".listing-title")
            property_type = self._text(card, ".listing-type")
            price_raw = self._text(card, ".listing-price")
            rooms_raw = self._text(card, ".listing-rooms")
            living_area_raw = self._text(card, ".listing-area")
            address_raw = self._text(card, ".listing-address")
            city_raw = self._text(card, ".listing-city")
            postal_code_raw = self._text(card, ".listing-postal-code")
            description_raw = self._text(card, ".listing-description")

            listings.append(
                RawListing(
                    source=self.source,
                    source_listing_id=source_listing_id,
                    url=url,
                    title=title,
                    property_type=property_type,
                    price_raw=price_raw,
                    rooms_raw=rooms_raw if rooms_raw and rooms_raw != "-" else None,
                    living_area_raw=living_area_raw,
                    address_raw=address_raw,
                    city_raw=city_raw,
                    postal_code_raw=postal_code_raw,
                    description_raw=description_raw,
                    raw_data={
                        "fixture": str(self.html_path),
                        "card_index": index,
                        "parser": "static_html",
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
