import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from immo_ne_collector.scrapers.base import BaseScraper, RawListing
from immo_ne_collector.services.source_config import infer_detected_canton


class HomegateParseError(RuntimeError):
    pass


HOMEGATE_CHALLENGE_MARKERS: tuple[str, ...] = (
    "just a moment",
    "checking your browser",
    "cloudflare",
    "cf-browser-verification",
    "challenge-platform",
)


def detect_homegate_challenge_html(html_text: str) -> tuple[bool, str | None]:
    lowered = html_text.lower()
    for marker in HOMEGATE_CHALLENGE_MARKERS:
        if marker in lowered:
            return True, marker
    return False, None


class HomegateCachedHtmlScraper(BaseScraper):
    source = "homegate"

    def __init__(
        self,
        *,
        html_path: Path,
        source: str | None = None,
        url_kind: str = "residential",
        base_url: str = "https://www.homegate.ch",
    ) -> None:
        self.html_path = Path(html_path)
        if source:
            self.source = source
        self.url_kind = url_kind.strip().lower() if url_kind else "residential"
        self.base_url = base_url
        super().__init__()

    async def collect(self) -> list[RawListing]:
        if not self.html_path.exists():
            raise HomegateParseError(f"Cached HTML file not found: {self.html_path}")
        html_text = self.html_path.read_text(encoding="utf-8")
        return self.parse_html(html_text)

    def parse_html(self, html_text: str) -> list[RawListing]:
        challenge_detected, challenge_reason = detect_homegate_challenge_html(html_text)
        if challenge_detected:
            raise HomegateParseError(
                f"Homegate challenge page detected ({challenge_reason}). "
                "Cached HTML is not directly parsable without anti-bot bypass, which is disabled in MVP."
            )

        soup = BeautifulSoup(html_text, "html.parser")
        page_context = self._detect_page_transaction_context(soup)
        fetched_at = datetime.now(UTC)
        initial_state_items = self._extract_initial_state_items(html_text)

        listings: list[RawListing] = []
        if initial_state_items:
            for idx, item in enumerate(initial_state_items, start=1):
                listing = self._raw_listing_from_initial_state(
                    item=item,
                    idx=idx,
                    page_context=page_context,
                    fetched_at=fetched_at,
                )
                if listing is not None:
                    listings.append(listing)

        if listings:
            return listings

        json_ld_items = self._extract_json_ld_items(soup)

        if json_ld_items:
            for idx, item in enumerate(json_ld_items, start=1):
                listing = self._raw_listing_from_json_ld(
                    item=item,
                    idx=idx,
                    page_context=page_context,
                    fetched_at=fetched_at,
                )
                if listing is not None:
                    listings.append(listing)

        if listings:
            return listings

        cards, strategy = self._find_listing_cards(soup)
        if not cards:
            raise HomegateParseError(
                "No Homegate listing cards found and window.__INITIAL_STATE__ is missing or not exploitable. "
                "Tried JSON-LD ItemList and selectors: "
                "article[data-test='result-item'], article[data-testid='result-item'], "
                "div[data-test='result-item'], li[data-test='result-item']."
            )

        for idx, card in enumerate(cards, start=1):
            href = self._extract_href(card)
            if not href:
                raise HomegateParseError(f"Missing listing URL in card #{idx}")
            url = urljoin(self.base_url, href)
            title = self._extract_title(card)
            description = self._extract_description(card)
            text_blob = self._collect_text(card)
            property_type = self._resolve_property_type(href=href, title=title)
            price_raw = self._extract_price(card, text_blob)
            rooms_raw = self._extract_rooms(card, text_blob)
            living_area_raw = self._extract_living_area(card, text_blob)
            city_raw, postal_code_raw = self._extract_city_and_postal(card, text_blob)
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

            listings.append(
                RawListing(
                    source=self.source,
                    source_listing_id=self._extract_listing_id_from_url(url),
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
                        "parser": "homegate_cached_html",
                        "strategy": strategy,
                        "parser_strategy": "html_fixture_fallback",
                        "page_transaction_context": page_context,
                        "transaction_type": transaction_type,
                        "challenge_detected": False,
                        "detected_canton": detected_canton,
                        "detected_canton_reason": detected_canton_reason,
                        "url_kind": self.url_kind,
                        "source_category": self.url_kind,
                    },
                    fetched_at=fetched_at,
                )
            )

        return listings

    def _find_listing_cards(self, soup: BeautifulSoup) -> tuple[list, str]:
        selectors = (
            ("article[data-test='result-item']", "article_data_test_result_item"),
            ("article[data-testid='result-item']", "article_data_testid_result_item"),
            ("div[data-test='result-item']", "div_data_test_result_item"),
            ("li[data-test='result-item']", "li_data_test_result_item"),
        )
        for selector, strategy in selectors:
            cards = soup.select(selector)
            if cards:
                return cards, strategy

        cards = [
            node
            for node in soup.select("article,div,li")
            if node.select_one("a[href]") and self._collect_text(node)
        ]
        if cards:
            return cards, "generic_container"

        return [], "none"

    def _extract_json_ld_items(self, soup: BeautifulSoup) -> list[dict]:
        items: list[dict] = []
        for script in soup.select("script[type='application/ld+json']"):
            raw = script.string or script.get_text("", strip=True)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            candidates = payload if isinstance(payload, list) else [payload]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                if candidate.get("@type") == "ItemList":
                    list_elements = candidate.get("itemListElement") or []
                    if isinstance(list_elements, list):
                        for entry in list_elements:
                            if not isinstance(entry, dict):
                                continue
                            item = entry.get("item") if isinstance(entry.get("item"), dict) else entry
                            if isinstance(item, dict):
                                items.append(item)
                elif candidate.get("@type") in {"Offer", "Product", "Residence", "House", "Apartment"}:
                    items.append(candidate)
        return items

    def _raw_listing_from_json_ld(
        self,
        *,
        item: dict,
        idx: int,
        page_context: str,
        fetched_at: datetime,
    ) -> RawListing | None:
        url_value = item.get("url")
        if not isinstance(url_value, str) or not url_value.strip():
            return None
        url = urljoin(self.base_url, url_value.strip())

        title = self._clean_text(item.get("name"))
        description = self._clean_text(item.get("description"))
        href = urlparse(url).path
        property_type = self._resolve_property_type(href=href, title=title)
        city_raw, postal_code_raw = self._extract_city_and_postal_from_json_ld(item)
        price_raw = self._extract_price_from_json_ld(item)
        rooms_raw = self._extract_rooms_from_json_ld(item)
        living_area_raw = self._extract_area_from_json_ld(item)
        address_raw = self._extract_address_from_json_ld(item)
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

        return RawListing(
            source=self.source,
            source_listing_id=self._extract_listing_id_from_url(url),
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
                "parser": "homegate_cached_html",
                "strategy": "json_ld_item_list",
                "parser_strategy": "json_ld_item_list",
                "page_transaction_context": page_context,
                "transaction_type": transaction_type,
                "challenge_detected": False,
                "detected_canton": detected_canton,
                "detected_canton_reason": detected_canton_reason,
                "url_kind": self.url_kind,
                "source_category": self.url_kind,
            },
            fetched_at=fetched_at,
        )

    def _raw_listing_from_initial_state(
        self,
        *,
        item: dict[str, Any],
        idx: int,
        page_context: str,
        fetched_at: datetime,
    ) -> RawListing | None:
        url_value = self._extract_url_from_initial_state(item)
        if url_value is None:
            return None
        url = urljoin(self.base_url, url_value)

        title = self._clean_text(self._coerce_str(self._extract_first_field(item, {"title", "name", "headline"})))
        description = self._clean_text(
            self._coerce_str(self._extract_first_field(item, {"description", "summary", "shortDescription"}))
        )

        price_value = self._extract_first_field(item, {"price", "pricevalue", "totalprice", "amount"})
        rooms_value = self._extract_first_field(item, {"rooms", "numberofrooms", "roomcount"})
        area_value = self._extract_first_field(item, {"livingarea", "surface", "area", "livingareasqm"})
        city_value = self._extract_first_field(item, {"city", "locality", "town"})
        postal_value = self._extract_first_field(item, {"postalcode", "zip", "zipcode"})
        address_value = self._extract_first_field(item, {"address", "street", "streetaddress"})
        property_type_value = self._extract_first_field(item, {"propertytype", "category", "listingtype", "type"})
        listing_id_value = self._extract_first_field(item, {"id", "listingid", "advertid", "objectid", "externalid"})

        property_type = self._resolve_property_type(
            href=urlparse(url).path,
            title=title,
            property_type_hint=self._coerce_str(property_type_value),
        )
        transaction_type = self._classify_transaction_type(
            href=urlparse(url).path,
            title=title,
            description=description,
            card_text="",
            page_context=page_context,
        )

        price_raw = self._format_price(price_value)
        rooms_raw = self._format_rooms(rooms_value)
        living_area_raw = self._format_area(area_value)
        city_raw = self._clean_text(self._coerce_str(city_value))
        postal_code_raw = self._extract_postal_code(self._coerce_str(postal_value))
        address_raw = self._clean_text(self._coerce_str(address_value))
        source_listing_id = self._normalize_source_listing_id(listing_id_value) or self._extract_listing_id_from_url(url)
        detected_canton, detected_canton_reason = infer_detected_canton(
            url=url,
            city=city_raw,
            postal_code=postal_code_raw,
        )

        return RawListing(
            source=self.source,
            source_listing_id=source_listing_id,
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
                "parser": "homegate_cached_html",
                "strategy": "initial_state_json",
                "parser_strategy": "initial_state_json",
                "page_transaction_context": page_context,
                "transaction_type": transaction_type,
                "challenge_detected": False,
                "detected_canton": detected_canton,
                "detected_canton_reason": detected_canton_reason,
                "url_kind": self.url_kind,
                "source_category": self.url_kind,
            },
            fetched_at=fetched_at,
        )

    @staticmethod
    def _clean_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = " ".join(value.split()).strip()
        return cleaned or None

    @staticmethod
    def _collect_text(card) -> str:
        return " ".join(card.get_text(" ", strip=True).split())

    def _extract_href(self, card) -> str | None:
        candidates = card.select("a[href]")
        if not candidates:
            return None
        best = None
        best_score = -1
        for anchor in candidates:
            href = (anchor.get("href") or "").strip()
            if not href:
                continue
            score = 0
            normalized = href.lower()
            if "/acheter/" in normalized or "/buy/" in normalized:
                score += 2
            if "liste-annonces" in normalized:
                score -= 2
            score += len(href)
            if score > best_score:
                best_score = score
                best = href
        return best

    def _extract_title(self, card) -> str | None:
        for selector in ("[data-test='result-title']", "[data-testid='result-title']", "h2", "h3"):
            node = card.select_one(selector)
            if node is None:
                continue
            text = self._clean_text(node.get_text(" ", strip=True))
            if text:
                return text
        return None

    def _extract_description(self, card) -> str | None:
        for selector in ("[data-test='result-description']", "[data-testid='result-description']", "p"):
            node = card.select_one(selector)
            if node is None:
                continue
            text = self._clean_text(node.get_text(" ", strip=True))
            if text:
                return text
        return None

    def _extract_price(self, card, text_blob: str) -> str | None:
        for selector in ("[data-test='result-price']", "[data-testid='result-price']", ".price"):
            node = card.select_one(selector)
            if node is None:
                continue
            text = self._clean_text(node.get_text(" ", strip=True))
            if text and self._looks_like_price(text):
                return text
        match = re.search(r"CHF\s*\d[\d '\u202f]*(?:\.-)?", text_blob, flags=re.IGNORECASE)
        if match:
            return match.group(0)
        return None

    @staticmethod
    def _looks_like_price(value: str) -> bool:
        digits = re.sub(r"\D", "", value)
        if not digits:
            return False
        try:
            amount = int(digits)
        except ValueError:
            return False
        return amount >= 10000

    def _extract_rooms(self, card, text_blob: str) -> str | None:
        for selector in ("[data-test='result-rooms']", "[data-testid='result-rooms']"):
            node = card.select_one(selector)
            if node is None:
                continue
            text = self._clean_text(node.get_text(" ", strip=True))
            if text and re.search(r"\d+(?:[.,]\d+)?\s*(?:pi[eè]ce(?:s)?|rooms?)", text, flags=re.IGNORECASE):
                return text
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:pi[eè]ce(?:s)?|rooms?)", text_blob, flags=re.IGNORECASE)
        if match:
            return match.group(0)
        return None

    def _extract_living_area(self, card, text_blob: str) -> str | None:
        for selector in ("[data-test='result-area']", "[data-testid='result-area']"):
            node = card.select_one(selector)
            if node is None:
                continue
            text = self._clean_text(node.get_text(" ", strip=True))
            if text and re.search(r"\d+(?:[.,]\d+)?\s*(?:m²|m2)\b", text, flags=re.IGNORECASE):
                return text
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:m²|m2)\b", text_blob, flags=re.IGNORECASE)
        if match:
            return match.group(0)
        return None

    def _extract_city_and_postal(self, card, text_blob: str) -> tuple[str | None, str | None]:
        location_text = None
        for selector in (
            "[data-test='result-address']",
            "[data-testid='result-address']",
            "[data-test='result-location']",
            "[data-testid='result-location']",
        ):
            node = card.select_one(selector)
            if node is None:
                continue
            location_text = self._clean_text(node.get_text(" ", strip=True))
            if location_text:
                break

        if location_text is None:
            location_text = text_blob

        postal_code = None
        postal_match = re.search(r"\b(\d{4})\b", location_text)
        if postal_match:
            postal_code = postal_match.group(1)

        city = None
        if postal_code:
            city_match = re.search(rf"\b{postal_code}\b\s+([A-Za-zÀ-ÖØ-öø-ÿ'\- ]+)", location_text)
            if city_match:
                city = self._clean_text(city_match.group(1))

        return city, postal_code

    def _extract_address(self, card) -> str | None:
        node = card.select_one("[data-test='result-address-full'], [data-testid='result-address-full']")
        if node is None:
            return None
        return self._clean_text(node.get_text(" ", strip=True))

    @staticmethod
    def _extract_listing_id_from_url(url: str) -> str:
        match = re.search(r"\b(\d{7,12})\b", url)
        if match:
            return match.group(1)
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        return f"url_{digest}"

    def _extract_property_type(
        self,
        *,
        href: str,
        title: str | None,
        property_type_hint: str | None = None,
    ) -> str | None:
        lowered_href = self._normalize_text(href)
        lowered_title = self._normalize_text(title)
        lowered_hint = self._normalize_text(property_type_hint)

        if lowered_hint:
            if any(token in lowered_hint for token in ("terrain", "land", "plot", "parcelle")):
                return "terrain"
            if any(token in lowered_hint for token in ("appartement", "apartment", "wohnung")):
                return "appartement"
            if any(token in lowered_hint for token in ("maison", "house", "villa", "haus")):
                return "maison"

        if "/terrain/" in lowered_href or " terrain " in f" {lowered_title} ":
            return "terrain"
        if "/appartement/" in lowered_href or "appartement" in lowered_title or "apartment" in lowered_title:
            return "appartement"
        if "/maison/" in lowered_href or "maison" in lowered_title or "villa" in lowered_title or "house" in lowered_title:
            return "maison"
        return None

    def _resolve_property_type(
        self,
        *,
        href: str,
        title: str | None,
        property_type_hint: str | None = None,
    ) -> str | None:
        if self.url_kind == "land":
            return "terrain"
        return self._extract_property_type(href=href, title=title, property_type_hint=property_type_hint)

    def _detect_page_transaction_context(self, soup: BeautifulSoup) -> str:
        title_text = soup.title.get_text(" ", strip=True) if soup.title else ""
        canonical_link = soup.select_one("link[rel='canonical']")
        canonical_href = canonical_link.get("href", "").strip() if canonical_link else ""
        full = self._normalize_text(f"{title_text} {canonical_href} {self.html_path}")

        has_buy = any(token in full for token in ("acheter", "buy", "kaufen", "acquistare"))
        has_rent = any(token in full for token in ("louer", "rent", "mieten", "affittare"))
        if has_buy and not has_rent:
            return "sale"
        if has_rent and not has_buy:
            return "rent"
        return "unknown"

    def _classify_transaction_type(
        self,
        *,
        href: str,
        title: str | None,
        description: str | None,
        card_text: str,
        page_context: str,
    ) -> str:
        combined = self._normalize_text(" ".join([href, title or "", description or "", card_text]))

        rent_keywords = (
            "location",
            "a louer",
            "louer",
            "sous-louer",
            "sous location",
            "loyer",
            "par mois",
            "/mois",
        )
        sale_keywords = (
            "a vendre",
            "vendre",
            "vente",
            "acheter",
            "buy",
        )
        has_rent = any(keyword in combined for keyword in rent_keywords)
        has_sale = any(keyword in combined for keyword in sale_keywords)

        if has_rent and has_sale:
            return "unknown"
        if has_rent:
            return "rent"
        if has_sale:
            return "sale"
        if page_context == "sale":
            return "sale"
        if page_context == "rent":
            return "rent"
        return "unknown"

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        text = (value or "").strip().lower().replace("à", "a")
        decomposed = unicodedata.normalize("NFKD", text)
        return "".join(ch for ch in decomposed if not unicodedata.combining(ch))

    def _extract_city_and_postal_from_json_ld(self, item: dict) -> tuple[str | None, str | None]:
        address = item.get("address")
        if not isinstance(address, dict):
            return None, None
        city = self._clean_text(address.get("addressLocality"))
        postal = self._clean_text(address.get("postalCode"))
        if postal and not re.fullmatch(r"\d{4}", postal):
            postal = None
        return city, postal

    def _extract_price_from_json_ld(self, item: dict) -> str | None:
        offers = item.get("offers")
        if not isinstance(offers, dict):
            return None
        price = offers.get("price")
        if isinstance(price, int | float):
            return f"CHF {int(price)}"
        if isinstance(price, str):
            cleaned = self._clean_text(price)
            if cleaned and self._looks_like_price(cleaned):
                return cleaned if "CHF" in cleaned.upper() else f"CHF {cleaned}"
        return None

    def _extract_rooms_from_json_ld(self, item: dict) -> str | None:
        rooms = item.get("numberOfRooms")
        if isinstance(rooms, int | float):
            if 1 <= float(rooms) <= 20:
                return f"{rooms} pièces"
        if isinstance(rooms, str):
            text = self._clean_text(rooms)
            if text and re.fullmatch(r"\d+(?:[.,]\d+)?", text):
                return f"{text} pièces"
        return None

    def _extract_area_from_json_ld(self, item: dict) -> str | None:
        area = item.get("floorSize")
        if isinstance(area, dict):
            value = area.get("value")
            unit = area.get("unitCode")
            if isinstance(value, int | float) and unit:
                return f"{value} m²"
        if isinstance(area, int | float):
            return f"{area} m²"
        return None

    def _extract_address_from_json_ld(self, item: dict) -> str | None:
        address = item.get("address")
        if not isinstance(address, dict):
            return None
        street = self._clean_text(address.get("streetAddress"))
        return street

    @staticmethod
    def _coerce_str(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = " ".join(value.split()).strip()
            return cleaned or None
        if isinstance(value, int | float):
            return str(value)
        return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            normalized = value.strip().replace("'", "").replace(" ", "").replace(",", ".")
            if not normalized:
                return None
            try:
                return float(normalized)
            except ValueError:
                return None
        return None

    @staticmethod
    def _normalize_source_listing_id(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return None

    @staticmethod
    def _extract_postal_code(value: str | None) -> str | None:
        if not value:
            return None
        match = re.search(r"\b(\d{4})\b", value)
        if match:
            return match.group(1)
        return None

    def _format_price(self, value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("amount", "value", "price", "total", "salePrice"):
                if key in value:
                    return self._format_price(value[key])
            return None
        numeric = self._coerce_float(value)
        if numeric is not None and numeric >= 10000:
            return f"CHF {int(round(numeric))}"
        text = self._coerce_str(value)
        if text and self._looks_like_price(text):
            return text if "CHF" in text.upper() else f"CHF {text}"
        return None

    def _format_rooms(self, value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("value", "amount", "rooms"):
                if key in value:
                    return self._format_rooms(value[key])
            return None
        numeric = self._coerce_float(value)
        if numeric is None:
            text = self._coerce_str(value)
            if text and re.fullmatch(r"\d+(?:[.,]\d+)?", text):
                numeric = float(text.replace(",", "."))
        if numeric is None:
            return None
        if not (0.5 <= numeric <= 20):
            return None
        formatted = str(int(numeric)) if numeric.is_integer() else str(numeric).rstrip("0").rstrip(".")
        return f"{formatted} pièces"

    def _format_area(self, value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("value", "amount", "sqm", "squareMeters", "area"):
                if key in value:
                    return self._format_area(value[key])
            return None
        numeric = self._coerce_float(value)
        if numeric is None:
            text = self._coerce_str(value)
            if text and re.fullmatch(r"\d+(?:[.,]\d+)?", text):
                numeric = float(text.replace(",", "."))
        if numeric is None:
            return None
        if not (10 <= numeric <= 10000):
            return None
        formatted = str(int(numeric)) if numeric.is_integer() else str(numeric).rstrip("0").rstrip(".")
        return f"{formatted} m²"

    def _extract_url_from_initial_state(self, item: dict[str, Any]) -> str | None:
        direct = self._extract_url_from_initial_state_direct(item)
        if direct:
            return direct
        for key in ("url", "listingUrl", "detailUrl", "href", "path"):
            value = self._extract_first_field(item, {self._normalize_key(key)})
            text = self._coerce_str(value)
            if not text:
                continue
            if text.startswith("/") or text.startswith("http://") or text.startswith("https://"):
                return text
        return None

    def _extract_url_from_initial_state_direct(self, item: dict[str, Any]) -> str | None:
        for key in ("url", "listingUrl", "detailUrl", "href", "path"):
            if key not in item:
                continue
            text = self._coerce_str(item.get(key))
            if not text:
                continue
            if text.startswith("/") or text.startswith("http://") or text.startswith("https://"):
                return text
        return None

    def _extract_first_field(self, data: Any, keys: set[str]) -> Any:
        if isinstance(data, dict):
            for raw_key, value in data.items():
                normalized_key = self._normalize_key(str(raw_key))
                if normalized_key in keys:
                    return value
                nested = self._extract_first_field(value, keys)
                if nested is not None:
                    return nested
        elif isinstance(data, list):
            for item in data:
                nested = self._extract_first_field(item, keys)
                if nested is not None:
                    return nested
        return None

    @staticmethod
    def _normalize_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    def _extract_initial_state_items(self, html_text: str) -> list[dict[str, Any]]:
        payload = self._extract_initial_state_payload(html_text)
        if payload is None:
            return []
        return self._find_initial_state_listing_nodes(payload)

    def _extract_initial_state_payload(self, html_text: str) -> dict[str, Any] | None:
        marker = "window.__INITIAL_STATE__"
        idx = html_text.find(marker)
        if idx == -1:
            return None
        eq_idx = html_text.find("=", idx)
        if eq_idx == -1:
            return None
        brace_start = html_text.find("{", eq_idx)
        if brace_start == -1:
            return None
        brace_end = self._find_balanced_json_end(html_text, brace_start)
        if brace_end is None:
            return None
        candidate = html_text[brace_start : brace_end + 1]
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if isinstance(loaded, dict):
            return loaded
        return None

    @staticmethod
    def _find_balanced_json_end(text: str, start: int) -> int | None:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == "\"":
                    in_string = False
                continue
            if ch == "\"":
                in_string = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return idx
        return None

    def _find_initial_state_listing_nodes(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        stack: list[Any] = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                url = self._extract_url_from_initial_state_direct(current)
                title = next(
                    (
                        self._coerce_str(current.get(key))
                        for key in ("title", "name", "headline")
                        if self._coerce_str(current.get(key))
                    ),
                    None,
                )
                if url and title:
                    items.append(current)
                    continue
                for value in current.values():
                    if isinstance(value, dict | list):
                        stack.append(value)
            elif isinstance(current, list):
                for value in current:
                    if isinstance(value, dict | list):
                        stack.append(value)
        deduped: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for item in items:
            url = self._extract_url_from_initial_state(item)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(item)
        return deduped
