from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from immo_ne_collector.scrapers.base import BaseScraper, RawListing
from immo_ne_collector.services.source_config import infer_detected_canton


class ImmoscoutParseError(RuntimeError):
    pass


IMMOSCOUT_CHALLENGE_MARKERS: tuple[str, ...] = (
    "just a moment",
    "checking your browser",
    "cloudflare",
    "cf-browser-verification",
    "challenge-platform",
    "attention required",
    "access denied",
)


def detect_immoscout_challenge_html(html_text: str) -> tuple[bool, str | None]:
    lowered = html_text.lower()
    for marker in IMMOSCOUT_CHALLENGE_MARKERS:
        if marker in lowered:
            return True, marker
    return False, None


class ImmoscoutCachedHtmlScraper(BaseScraper):
    source = "immoscout"

    def __init__(
        self,
        *,
        html_path: Path,
        source: str | None = None,
        url_kind: str = "residential",
        base_url: str = "https://www.immoscout24.ch",
    ) -> None:
        self.html_path = Path(html_path)
        if source:
            self.source = source
        self.url_kind = (url_kind or "residential").strip().lower()
        self.base_url = base_url
        super().__init__()

    async def collect(self) -> list[RawListing]:
        if not self.html_path.exists():
            raise ImmoscoutParseError(f"Cached HTML file not found: {self.html_path}")
        html_text = self.html_path.read_text(encoding="utf-8")
        return self.parse_html(html_text)

    def parse_html(self, html_text: str) -> list[RawListing]:
        challenge_detected, challenge_reason = detect_immoscout_challenge_html(html_text)
        if challenge_detected:
            raise ImmoscoutParseError(
                f"ImmoScout challenge page detected ({challenge_reason}). "
                "Cached HTML is not directly parsable in prudent MVP mode."
            )

        soup = BeautifulSoup(html_text, "html.parser")
        fetched_at = datetime.now(UTC)
        page_context = self._detect_page_transaction_context(soup, html_text)
        listings: list[RawListing] = []

        for idx, payload in enumerate(self._extract_structured_candidates(soup, html_text), start=1):
            listing = self._raw_listing_from_payload(
                payload=payload,
                idx=idx,
                page_context=page_context,
                fetched_at=fetched_at,
                parser_strategy="initial_state_json",
            )
            if listing is not None:
                listings.append(listing)
        if listings:
            return listings

        cards, strategy = self._find_listing_cards(soup)
        if not cards:
            raise ImmoscoutParseError(
                "No ImmoScout listing cards found and no structured payload exploitable. "
                "Expected selectors: article[data-listing-id], article[data-testid='result-list-item'], "
                "div[data-listing-id], li[data-listing-id], a[href*='/acheter/']."
            )

        for idx, card in enumerate(cards, start=1):
            href = self._extract_href(card)
            if not href:
                continue
            url = urljoin(self.base_url, href)
            title = self._extract_title(card) or self._infer_title_from_url(url)
            description = self._extract_description(card)
            text_blob = self._collect_text(card)
            property_type = self._resolve_property_type(
                explicit=self._extract_property_type(card),
                href=href,
                title=title,
            )
            price_raw = self._extract_price(card, text_blob)
            rooms_raw = self._extract_rooms(card, text_blob)
            living_area_raw = self._extract_living_area(card, text_blob)
            city_raw, postal_code_raw = self._extract_city_and_postal(card, text_blob, href)
            address_raw = self._extract_address(card)
            transaction_type = self._classify_transaction_type(
                href=href,
                title=title,
                description=description,
                card_text=text_blob,
                page_context=page_context,
            )
            detected_canton, detected_canton_reason = infer_detected_canton(
                url=url,
                city=city_raw,
                postal_code=postal_code_raw,
            )
            listing_id = self._extract_listing_id(url) or self._derive_stable_id(url)

            listings.append(
                RawListing(
                    source=self.source,
                    source_listing_id=listing_id,
                    url=url,
                    title=title,
                    property_type=property_type,
                    price_raw=price_raw,
                    rooms_raw=rooms_raw,
                    living_area_raw=living_area_raw,
                    address_raw=address_raw,
                    city_raw=city_raw,
                    postal_code_raw=postal_code_raw,
                    description_raw=description,
                    raw_data={
                        "fixture_or_cache_path": str(self.html_path),
                        "card_index": idx,
                        "parser": "immoscout_cached_html",
                        "strategy": strategy,
                        "parser_strategy": "html_fixture_fallback",
                        "page_transaction_context": page_context,
                        "transaction_type": transaction_type,
                        "detected_canton": detected_canton,
                        "detected_canton_reason": detected_canton_reason,
                        "challenge_detected": False,
                        "url_kind": self.url_kind,
                        "source_category": self.url_kind,
                    },
                    fetched_at=fetched_at,
                )
            )

        if not listings:
            raise ImmoscoutParseError(
                "No ImmoScout listings extracted from available HTML blocks."
            )
        return listings

    def _find_listing_cards(self, soup: BeautifulSoup) -> tuple[list, str]:
        selectors = (
            ("article[data-listing-id]", "article_data_listing_id"),
            ("article[data-testid='result-list-item']", "article_result_list_item"),
            ("article[data-test='result-item']", "article_result_item"),
            ("div[data-listing-id]", "div_data_listing_id"),
            ("li[data-listing-id]", "li_data_listing_id"),
            ("a[href*='/acheter/']", "anchor_acheter"),
            ("a[href*='/buy/']", "anchor_buy"),
        )
        for selector, strategy in selectors:
            cards = soup.select(selector)
            if cards:
                return cards, strategy
        return [], "none"

    def _extract_structured_candidates(self, soup: BeautifulSoup, html_text: str) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for script in soup.select("script[type='application/ld+json']"):
            raw = script.string or script.get_text("", strip=True)
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            payloads.extend(self._extract_listing_like_dicts(parsed))

        for marker in ("window.__INITIAL_STATE__", "window.__NEXT_DATA__"):
            embedded = self._extract_embedded_json_object(html_text, marker)
            if embedded is not None:
                payloads.extend(self._extract_listing_like_dicts(embedded))

        return payloads

    def _extract_listing_like_dicts(self, payload: Any) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if self._looks_like_listing_payload(value):
                    nodes.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)
        return nodes

    @staticmethod
    def _looks_like_listing_payload(payload: dict[str, Any]) -> bool:
        url_value = payload.get("url") or payload.get("href") or payload.get("detailUrl")
        if not isinstance(url_value, str) or not url_value.strip():
            return False
        listing_keys = {"title", "name", "propertyType", "price", "offerType", "address", "rooms", "livingArea"}
        return any(key in payload for key in listing_keys)

    @staticmethod
    def _extract_embedded_json_object(html_text: str, marker: str) -> dict[str, Any] | None:
        marker_idx = html_text.find(marker)
        if marker_idx < 0:
            return None
        equal_idx = html_text.find("=", marker_idx)
        if equal_idx < 0:
            return None
        brace_start = html_text.find("{", equal_idx)
        if brace_start < 0:
            return None

        depth = 0
        in_string = False
        escaped = False
        end_idx = -1
        for i in range(brace_start, len(html_text)):
            char = html_text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == "\"":
                    in_string = False
                continue
            if char == "\"":
                in_string = True
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break
        if end_idx < 0:
            return None
        raw = html_text[brace_start:end_idx + 1]
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    def _raw_listing_from_payload(
        self,
        *,
        payload: dict[str, Any],
        idx: int,
        page_context: str,
        fetched_at: datetime,
        parser_strategy: str,
    ) -> RawListing | None:
        href = self._first_text(payload, "url", "href", "detailUrl")
        if not href:
            return None
        url = urljoin(self.base_url, href)
        title = self._first_text(payload, "title", "name", "headline") or self._infer_title_from_url(url)
        description = self._first_text(payload, "description")
        property_type = self._resolve_property_type(
            explicit=self._first_text(payload, "propertyType", "category"),
            href=href,
            title=title,
        )
        price_raw = self._to_price_raw(payload.get("price") or payload.get("priceValue"))
        rooms_raw = self._to_rooms_raw(payload.get("rooms") or payload.get("numberOfRooms"))
        living_area_raw = self._to_area_raw(payload.get("livingArea") or payload.get("surface") or payload.get("area"))
        city_raw, postal_code_raw, address_raw = self._extract_location_from_payload(payload)
        transaction_type = self._classify_transaction_type(
            href=href,
            title=title,
            description=description,
            card_text="",
            page_context=page_context,
        )
        detected_canton, detected_canton_reason = infer_detected_canton(
            url=url,
            city=city_raw,
            postal_code=postal_code_raw,
        )
        listing_id = self._extract_listing_id(url) or self._derive_stable_id(url)

        return RawListing(
            source=self.source,
            source_listing_id=listing_id,
            url=url,
            title=title,
            property_type=property_type,
            price_raw=price_raw,
            rooms_raw=rooms_raw,
            living_area_raw=living_area_raw,
            address_raw=address_raw,
            city_raw=city_raw,
            postal_code_raw=postal_code_raw,
            description_raw=description,
            raw_data={
                "fixture_or_cache_path": str(self.html_path),
                "card_index": idx,
                "parser": "immoscout_cached_html",
                "strategy": "structured_payload",
                "parser_strategy": parser_strategy,
                "page_transaction_context": page_context,
                "transaction_type": transaction_type,
                "detected_canton": detected_canton,
                "detected_canton_reason": detected_canton_reason,
                "challenge_detected": False,
                "url_kind": self.url_kind,
                "source_category": self.url_kind,
            },
            fetched_at=fetched_at,
        )

    @staticmethod
    def _first_text(payload: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str):
                cleaned = " ".join(value.split())
                if cleaned:
                    return cleaned
        return None

    def _extract_location_from_payload(self, payload: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
        address_obj = payload.get("address")
        if not isinstance(address_obj, dict):
            return None, None, None
        city = self._first_text(address_obj, "city", "addressLocality", "locality")
        postal_code = self._first_text(address_obj, "postalCode", "zip")
        street = self._first_text(address_obj, "street", "streetAddress")
        if street and city:
            address = f"{street}, {city}"
        else:
            address = street
        return city, postal_code, address

    def _extract_href(self, card) -> str | None:
        if card.name == "a":
            href = (card.get("href") or "").strip()
            return href or None
        link = card.select_one("a[href]")
        if link is None:
            return None
        href = (link.get("href") or "").strip()
        return href or None

    def _extract_title(self, card) -> str | None:
        for selector in (".immoscout-title", "[data-test='result-title']", "h2", "h3"):
            node = card.select_one(selector)
            if node is not None:
                text = " ".join(node.get_text(" ", strip=True).split())
                if text:
                    return text
        return None

    def _extract_description(self, card) -> str | None:
        for selector in (".immoscout-description", "[data-test='result-description']", "p"):
            node = card.select_one(selector)
            if node is not None:
                text = " ".join(node.get_text(" ", strip=True).split())
                if text:
                    return text
        return None

    def _extract_property_type(self, card) -> str | None:
        for selector in (".immoscout-property-type", "[data-test='property-type']"):
            node = card.select_one(selector)
            if node is not None:
                text = " ".join(node.get_text(" ", strip=True).split())
                if text:
                    return text
        return None

    def _resolve_property_type(self, *, explicit: str | None, href: str, title: str | None) -> str | None:
        if self.url_kind == "land":
            return "terrain"
        text = " ".join([explicit or "", href or "", title or ""]).lower()
        if "terrain" in text or "parcelle" in text or "/terrain" in text:
            return "terrain"
        if "maison" in text or "house" in text:
            return "maison"
        if "appartement" in text or "wohnung" in text or "apartment" in text:
            return "appartement"
        return explicit

    def _extract_price(self, card, text_blob: str) -> str | None:
        for selector in (".immoscout-price", "[data-test='result-price']"):
            node = card.select_one(selector)
            if node is not None:
                text = " ".join(node.get_text(" ", strip=True).split())
                if text and "chf" in text.lower():
                    return text
        match = re.search(r"\bCHF\s*[\d'\s]+(?:\.\-)?\b", text_blob, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
        return None

    def _extract_rooms(self, card, text_blob: str) -> str | None:
        for selector in (".immoscout-rooms", "[data-test='result-rooms']"):
            node = card.select_one(selector)
            if node is not None:
                text = " ".join(node.get_text(" ", strip=True).split())
                if text:
                    return text
        match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(?:pi[eè]ces?|rooms?)\b", text_blob, flags=re.IGNORECASE)
        if match:
            return f"{match.group(1)} pièces"
        return None

    def _extract_living_area(self, card, text_blob: str) -> str | None:
        for selector in (".immoscout-area", "[data-test='result-area']"):
            node = card.select_one(selector)
            if node is not None:
                text = " ".join(node.get_text(" ", strip=True).split())
                if text:
                    return text
        match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(?:m²|m2)\b", text_blob, flags=re.IGNORECASE)
        if match:
            return f"{match.group(1)} m2"
        return None

    def _extract_city_and_postal(self, card, text_blob: str, href: str) -> tuple[str | None, str | None]:
        city = None
        postal_code = None
        for selector in (".immoscout-city", "[data-test='result-city']", "[data-test='result-address']"):
            node = card.select_one(selector)
            if node is None:
                continue
            text = " ".join(node.get_text(" ", strip=True).split())
            if not text:
                continue
            postal_match = re.search(r"\b(\d{4})\b", text)
            if postal_match:
                postal_code = postal_match.group(1)
            city_candidate = re.sub(r"\b\d{4}\b", "", text).strip(" ,")
            if city_candidate:
                city = city_candidate
                break
        if city is None:
            city = self._infer_city_from_url(href)
        if postal_code is None:
            postal_match = re.search(r"\b(\d{4})\b", text_blob)
            if postal_match:
                postal_code = postal_match.group(1)
        return city, postal_code

    def _extract_address(self, card) -> str | None:
        node = card.select_one(".immoscout-address") or card.select_one("[data-test='result-address']")
        if node is None:
            return None
        text = " ".join(node.get_text(" ", strip=True).split())
        return text or None

    @staticmethod
    def _collect_text(card) -> str:
        return " ".join(card.get_text(" ", strip=True).split())

    @staticmethod
    def _to_price_raw(value: Any) -> str | None:
        if isinstance(value, int | float):
            return f"CHF {int(value)}"
        if isinstance(value, str):
            cleaned = " ".join(value.split())
            if not cleaned:
                return None
            return cleaned if "chf" in cleaned.lower() else f"CHF {cleaned}"
        return None

    @staticmethod
    def _to_rooms_raw(value: Any) -> str | None:
        if isinstance(value, int | float):
            return f"{value} pièces"
        if isinstance(value, str):
            cleaned = " ".join(value.split())
            return cleaned or None
        return None

    @staticmethod
    def _to_area_raw(value: Any) -> str | None:
        if isinstance(value, int | float):
            return f"{value} m2"
        if isinstance(value, str):
            cleaned = " ".join(value.split())
            return cleaned or None
        return None

    @staticmethod
    def _extract_listing_id(url: str) -> str | None:
        match = re.search(r"(?:listing-|/)(\d{6,})(?:[/?#]|$)", url)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _derive_stable_id(value: str) -> str:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
        return f"url_{digest}"

    @staticmethod
    def _infer_title_from_url(url: str) -> str | None:
        parts = [part for part in url.split("/") if part]
        if not parts:
            return None
        slug = parts[-1]
        slug = re.sub(r",?\d+$", "", slug)
        cleaned = slug.replace("-", " ").strip()
        if not cleaned:
            return None
        return cleaned[:1].upper() + cleaned[1:]

    @staticmethod
    def _infer_city_from_url(text: str) -> str | None:
        match = re.search(r"dans[-/ ]([a-zA-Z\-\u00C0-\u017F]+)", text, flags=re.IGNORECASE)
        if not match:
            return None
        value = match.group(1).replace("-", " ").strip()
        if not value:
            return None
        return value[:1].upper() + value[1:]

    @staticmethod
    def _detect_page_transaction_context(soup: BeautifulSoup, html_text: str) -> str:
        haystack = " ".join(
            [
                soup.title.get_text(" ", strip=True) if soup.title else "",
                " ".join(node.get_text(" ", strip=True) for node in soup.select("h1")),
                html_text[:2000],
            ]
        ).lower()
        if "acheter" in haystack or "buy" in haystack or "vente" in haystack:
            return "sale"
        if "louer" in haystack or "rent" in haystack or "location" in haystack:
            return "rent"
        return "unknown"

    @staticmethod
    def _classify_transaction_type(
        *,
        href: str,
        title: str | None,
        description: str | None,
        card_text: str,
        page_context: str,
    ) -> str:
        haystack = " ".join([href or "", title or "", description or "", card_text or ""]).lower()
        rent_markers = ("a louer", "à louer", "location", "sous-location", "loyer", "/louer/", "/rent/")
        if any(marker in haystack for marker in rent_markers):
            return "rent"
        sale_markers = ("acheter", "a vendre", "à vendre", "vente", "/acheter/", "/buy/")
        if any(marker in haystack for marker in sale_markers):
            return "sale"
        if page_context in {"sale", "rent"}:
            return page_context
        return "unknown"
