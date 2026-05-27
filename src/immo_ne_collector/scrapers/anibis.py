import hashlib
import re
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
        strategy = "fixture_cards"
        if not cards:
            cards = soup.select("div[data-private-srp-listing-item-id]")
            strategy = "srp_private_cards"

        if not cards:
            raise AnibisParseError(
                "No Anibis listing cards found. Tried selectors: "
                "article.anibis-card[data-item-id], div[data-private-srp-listing-item-id]."
            )

        fetched_at = datetime.now(UTC)
        listings: list[RawListing] = []
        for idx, card in enumerate(cards, start=1):
            source_listing_id, href = self._extract_id_and_href(card)
            if not href:
                raise AnibisParseError(f"Missing listing URL in card #{idx}")

            listings.append(
                RawListing(
                    source=self.source,
                    source_listing_id=source_listing_id or self._derive_stable_id(href),
                    url=urljoin(self.base_url, href),
                    title=self._extract_title(card),
                    property_type=self._extract_property_type(card, href),
                    price_raw=self._extract_price(card),
                    rooms_raw=self._extract_rooms(card),
                    living_area_raw=self._extract_living_area(card),
                    address_raw=self._extract_address(card),
                    city_raw=self._extract_city(card),
                    postal_code_raw=self._extract_postal_code(card),
                    description_raw=self._extract_description(card),
                    raw_data={
                        "fixture_or_cache_path": str(self.html_path),
                        "card_index": idx,
                        "parser": "anibis_cached_html",
                        "strategy": strategy,
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

    def _extract_id_and_href(self, card) -> tuple[str | None, str]:
        source_listing_id = card.get("data-item-id") or card.get("data-private-srp-listing-item-id")

        link = (
            card.select_one("h2 a[href]")
            or card.select_one("a.anibis-link[href]")
            or card.select_one("a[href]")
        )
        href = link.get("href", "").strip() if link else ""

        if not source_listing_id:
            source_listing_id = self._extract_id_from_href(href)
        return source_listing_id, href

    @staticmethod
    def _extract_id_from_href(href: str) -> str | None:
        if not href:
            return None
        match = re.search(r"/(\d+)(?:[/?#]|$)", href)
        return match.group(1) if match else None

    @staticmethod
    def _derive_stable_id(href: str) -> str:
        digest = hashlib.sha1(href.encode("utf-8")).hexdigest()[:16]
        return f"url_{digest}"

    def _extract_title(self, card) -> str | None:
        return self._text(card, ".anibis-title") or self._text(card, "h2")

    def _extract_property_type(self, card, href: str) -> str | None:
        explicit = self._text(card, ".anibis-type")
        if explicit:
            return explicit
        lowered_href = href.lower()
        if "/immobilier/appartements/" in lowered_href:
            return "appartement"
        if "/immobilier/maisons/" in lowered_href:
            return "maison"
        return None

    def _extract_price(self, card) -> str | None:
        return self._text(card, ".anibis-price") or self._find_text_matching(
            card,
            r"\d[\d '\u202f]*\.-",
        )

    def _extract_rooms(self, card) -> str | None:
        return self._text(card, ".anibis-rooms") or self._find_text_matching(
            card,
            r"\d+(?:[.,]\d+)?\s*(?:pi[eè]ce(?:s)?|pce(?:s)?)",
        )

    def _extract_living_area(self, card) -> str | None:
        return self._text(card, ".anibis-area") or self._find_text_matching(
            card,
            r"\d+(?:[.,]\d+)?\s*(?:m²|m2)\b",
        )

    def _extract_address(self, card) -> str | None:
        return self._text(card, ".anibis-address")

    def _extract_city(self, card) -> str | None:
        explicit = self._text(card, ".anibis-city")
        if explicit:
            return explicit
        location_text = self._extract_location_text(card)
        if not location_text:
            return None
        parts = [part.strip() for part in location_text.split(",")]
        return parts[0] or None

    def _extract_postal_code(self, card) -> str | None:
        explicit = self._text(card, ".anibis-postal")
        if explicit:
            return explicit
        location_text = self._extract_location_text(card)
        if not location_text:
            return None
        match = re.search(r"\b(\d{4})\b", location_text)
        return match.group(1) if match else None

    def _extract_description(self, card) -> str | None:
        return self._text(card, ".anibis-description") or self._extract_longest_text_span(card)

    def _extract_location_text(self, card) -> str | None:
        node = card.select_one("span.mui-style-hz3olr")
        if node is not None:
            cleaned = " ".join(node.get_text(" ", strip=True).split())
            return cleaned or None
        span_texts = self._span_texts(card)
        return span_texts[0] if span_texts else None

    def _extract_longest_text_span(self, card) -> str | None:
        span_texts = self._span_texts(card)
        if not span_texts:
            return None
        return max(span_texts, key=len)

    def _span_texts(self, card) -> list[str]:
        texts: list[str] = []
        for node in card.select("span"):
            cleaned = " ".join(node.get_text(" ", strip=True).split())
            if cleaned:
                texts.append(cleaned)
        return texts

    def _find_text_matching(self, card, pattern: str) -> str | None:
        regex = re.compile(pattern, flags=re.IGNORECASE)
        for text in self._span_texts(card):
            match = regex.search(text)
            if match:
                return match.group(0)
        return None
