import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from immo_ne_collector.scrapers.base import BaseScraper, RawListing
from immo_ne_collector.scrapers.lookmove_utils import (
    classify_transaction_type,
    derive_stable_id_from_url,
    detect_page_transaction_context,
    extract_lookmove_listing_id,
    infer_city_from_href,
    infer_postal_code_from_city,
    infer_property_type_from_href,
    infer_title_from_href,
)
from immo_ne_collector.services.source_config import infer_detected_canton


class LookmoveParseError(RuntimeError):
    pass


class LookmoveCachedHtmlScraper(BaseScraper):
    source = "lookmove"

    def __init__(
        self,
        *,
        html_path: Path,
        source: str | None = None,
        base_url: str = "https://www.lookmove.ch",
    ) -> None:
        self.html_path = Path(html_path)
        if source:
            self.source = source
        self.base_url = base_url
        super().__init__()

    async def collect(self) -> list[RawListing]:
        if not self.html_path.exists():
            raise LookmoveParseError(f"Cached HTML file not found: {self.html_path}")
        html_text = self.html_path.read_text(encoding="utf-8")
        return self.parse_html(html_text)

    def parse_html(self, html_text: str) -> list[RawListing]:
        soup = BeautifulSoup(html_text, "html.parser")
        page_context = self._detect_page_context(soup, html_text)
        offers_by_id = self._extract_offer_index(html_text)

        cards, strategy = self._find_listing_cards(soup)
        if not cards:
            raise LookmoveParseError(
                "No Lookmove listing cards found. Tried selectors: "
                "article.lookmove-card[data-listing-id], article[data-listing-id], "
                "div[data-listing-id], a[href*='/listing/'], a[href*='/annonce/']."
            )

        fetched_at = datetime.now(UTC)
        listings: list[RawListing] = []

        for idx, card in enumerate(cards, start=1):
            source_listing_id, href = self._extract_id_and_href(card, strategy)
            if not href:
                raise LookmoveParseError(f"Missing listing URL in card #{idx}")

            url = urljoin(self.base_url, href)
            listing_id = source_listing_id or extract_lookmove_listing_id(url) or derive_stable_id_from_url(url)
            offer_data = offers_by_id.get(str(listing_id))

            title = self._extract_title(card) or infer_title_from_href(href)
            description = self._extract_description(card)
            property_type = self._extract_property_type(card, href)
            city = self._extract_city(card) or infer_city_from_href(href)
            postal_code = self._extract_postal_code(card) or infer_postal_code_from_city(city)
            price_raw, detected_price_text, rejected_price_reason = self._extract_price(card, offer_data)
            rooms_raw, detected_rooms_text, rejected_rooms_reason = self._extract_rooms(card, offer_data)
            area_raw, detected_area_text, rejected_area_reason = self._extract_living_area(card, offer_data)
            card_text = " ".join(card.get_text(" ", strip=True).split())
            transaction_type = classify_transaction_type(
                href=href,
                title=title,
                description=description,
                card_text=card_text,
                page_context=page_context,
            )
            detected_canton, detected_canton_reason = infer_detected_canton(
                url=url,
                city=city,
                postal_code=postal_code,
            )

            listings.append(
                RawListing(
                    source=self.source,
                    source_listing_id=listing_id,
                    url=url,
                    title=title,
                    property_type=property_type,
                    price_raw=price_raw,
                    rooms_raw=rooms_raw,
                    living_area_raw=area_raw,
                    address_raw=self._extract_address(card),
                    city_raw=city,
                    postal_code_raw=postal_code,
                    description_raw=description,
                    raw_data={
                        "fixture_or_cache_path": str(self.html_path),
                        "card_index": idx,
                        "parser": "lookmove_cached_html",
                        "strategy": strategy,
                        "page_transaction_context": page_context,
                        "transaction_type": transaction_type,
                        "detected_canton": detected_canton,
                        "detected_canton_reason": detected_canton_reason,
                        "detected_title": title,
                        "detected_city": city,
                        "detected_postal_code": postal_code,
                        "detected_price_text": detected_price_text,
                        "detected_rooms_text": detected_rooms_text,
                        "detected_area_text": detected_area_text,
                        "rejected_price_reason": rejected_price_reason,
                        "rejected_rooms_reason": rejected_rooms_reason,
                        "rejected_area_reason": rejected_area_reason,
                        "source_reason": "window_app_coords_result" if offer_data is not None else "html_only",
                    },
                    fetched_at=fetched_at,
                )
            )

        return listings

    def _find_listing_cards(self, soup: BeautifulSoup) -> tuple[list, str]:
        selectors = (
            ("article.lookmove-card[data-listing-id]", "fixture_cards"),
            ("article[data-listing-id]", "article_data_listing_id"),
            ("div[data-listing-id]", "div_data_listing_id"),
        )
        for selector, strategy in selectors:
            cards = soup.select(selector)
            if cards:
                return cards, strategy

        anchors = soup.select("a[href*='/listing/'], a[href*='/annonce/']")
        if anchors:
            return anchors, "listing_anchors"

        return [], "none"

    def _extract_id_and_href(self, card, strategy: str) -> tuple[str | None, str]:
        if strategy == "listing_anchors":
            href = (card.get("href") or "").strip()
            source_listing_id = extract_lookmove_listing_id(href)
            return source_listing_id, href

        source_listing_id = (
            card.get("data-listing-id")
            or card.get("data-id")
            or card.get("data-item-id")
        )
        link = card.select_one("a[href]")
        href = link.get("href", "").strip() if link else ""
        if not source_listing_id:
            source_listing_id = extract_lookmove_listing_id(href)
        return source_listing_id, href

    @staticmethod
    def _text(card, selector: str) -> str | None:
        node = card.select_one(selector)
        if node is None:
            return None
        cleaned = " ".join(node.get_text(" ", strip=True).split())
        return cleaned or None

    def _extract_title(self, card) -> str | None:
        return (
            self._text(card, ".lookmove-title")
            or self._text(card, "h2")
            or self._text(card, "h3")
        )

    def _extract_property_type(self, card, href: str) -> str | None:
        explicit = self._text(card, ".lookmove-property-type")
        if explicit:
            return explicit
        return infer_property_type_from_href(href)

    def _extract_price(self, card, offer_data: dict | None) -> tuple[str | None, str | None, str | None]:
        if offer_data is not None:
            raw_price = offer_data.get("price")
            if isinstance(raw_price, int | float):
                if raw_price >= 10000:
                    return f"CHF {int(raw_price)}", str(raw_price), None
                return None, str(raw_price), "offer_price_too_small"
            return None, None, "offer_price_missing"

        explicit = self._text(card, ".lookmove-price")
        if explicit:
            candidate = self._extract_price_from_text(explicit)
            if candidate is not None:
                return candidate, explicit, None
            return None, explicit, "price_text_rejected"
        return None, None, "price_not_found"

    def _extract_rooms(self, card, offer_data: dict | None) -> tuple[str | None, str | None, str | None]:
        if offer_data is not None:
            raw_rooms = offer_data.get("rooms")
            if isinstance(raw_rooms, int | float):
                if 1 <= float(raw_rooms) <= 20:
                    return f"{raw_rooms} pièces", str(raw_rooms), None
                return None, str(raw_rooms), "offer_rooms_out_of_range"
            return None, None, "offer_rooms_missing"

        explicit = self._text(card, ".lookmove-rooms")
        if explicit:
            candidate = self._extract_rooms_from_text(explicit)
            if candidate is not None:
                return candidate, explicit, None
            return None, explicit, "rooms_text_rejected"
        return None, None, "rooms_not_found"

    def _extract_living_area(self, card, offer_data: dict | None) -> tuple[str | None, str | None, str | None]:
        if offer_data is not None:
            raw_area = offer_data.get("livingSpace")
            if isinstance(raw_area, int | float):
                if 10 <= float(raw_area) <= 5000:
                    return f"{raw_area} m²", str(raw_area), None
                return None, str(raw_area), "offer_area_out_of_range"
            return None, None, "offer_area_missing"

        explicit = self._text(card, ".lookmove-area")
        if explicit:
            candidate = self._extract_area_from_text(explicit)
            if candidate is not None:
                return candidate, explicit, None
            return None, explicit, "area_text_rejected"
        return None, None, "area_not_found"

    def _extract_address(self, card) -> str | None:
        return self._text(card, ".lookmove-address")

    def _extract_city(self, card) -> str | None:
        explicit = self._text(card, ".lookmove-city")
        if explicit:
            return explicit

        location = self._text(card, ".lookmove-location")
        if location:
            parts = [part.strip() for part in location.split(",")]
            return parts[0] or None

        return None

    def _extract_postal_code(self, card) -> str | None:
        explicit = self._text(card, ".lookmove-postal-code")
        if explicit:
            match = re.search(r"\b(\d{4})\b", explicit)
            return match.group(1) if match else None

        location = self._text(card, ".lookmove-location")
        if not location:
            return None
        match = re.search(r"\b(\d{4})\b", location)
        return match.group(1) if match else None

    def _extract_description(self, card) -> str | None:
        return self._text(card, ".lookmove-description")

    @staticmethod
    def _extract_price_from_text(text: str) -> str | None:
        normalized = " ".join(text.split())
        chf_match = re.search(r"CHF\s*\d[\d '\u202f]*(?:\.-)?", normalized, flags=re.IGNORECASE)
        if chf_match:
            return chf_match.group(0)

        numeric_match = re.search(r"\b\d{5,}(?:\.-)?\b", normalized)
        if numeric_match:
            value = int(re.sub(r"\D", "", numeric_match.group(0)))
            if value >= 10000:
                return numeric_match.group(0)
        return None

    @staticmethod
    def _extract_rooms_from_text(text: str) -> str | None:
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:pi[eè]ce(?:s)?|pcs?)", text, flags=re.IGNORECASE)
        if not match:
            return None
        value = float(match.group(1).replace(",", "."))
        if 1 <= value <= 20:
            return match.group(0)
        return None

    @staticmethod
    def _extract_area_from_text(text: str) -> str | None:
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:m²|m2)\b", text, flags=re.IGNORECASE)
        if not match:
            return None
        value = float(match.group(1).replace(",", "."))
        if 10 <= value <= 5000:
            return match.group(0)
        return None

    @staticmethod
    def _extract_offer_index(html_text: str) -> dict[str, dict]:
        match = re.search(r"<script[^>]*>window\.App=(\{.*?\})</script>", html_text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}

        coords = (payload.get("state") or {}).get("coords") or {}
        result = coords.get("result") or []
        index: dict[str, dict] = {}
        for item in result:
            if not isinstance(item, dict):
                continue
            offer_id = item.get("id")
            if offer_id is None:
                continue
            index[str(offer_id)] = item
        return index

    def _detect_page_context(self, soup: BeautifulSoup, html_text: str) -> str:
        title_text = soup.title.get_text(" ", strip=True) if soup.title else ""
        canonical = soup.select_one("link[rel='canonical']")
        canonical_href = canonical.get("href", "") if canonical else ""
        context_text = " ".join([title_text, canonical_href, str(self.html_path), html_text[:1500]])
        return detect_page_transaction_context(context_text)
