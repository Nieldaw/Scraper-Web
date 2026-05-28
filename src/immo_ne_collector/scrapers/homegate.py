import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from immo_ne_collector.scrapers.base import BaseScraper, RawListing
from immo_ne_collector.services.source_config import infer_detected_canton


class HomegateParseError(RuntimeError):
    pass


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
        soup = BeautifulSoup(html_text, "html.parser")
        page_context = self._detect_page_transaction_context(soup)
        fetched_at = datetime.now(UTC)

        json_ld_items = self._extract_json_ld_items(soup)
        listings: list[RawListing] = []

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
                "No Homegate listing cards found. Tried JSON-LD ItemList and selectors: "
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
                        "page_transaction_context": page_context,
                        "transaction_type": transaction_type,
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
                "page_transaction_context": page_context,
                "transaction_type": transaction_type,
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

    def _extract_property_type(self, *, href: str, title: str | None) -> str | None:
        lowered_href = self._normalize_text(href)
        lowered_title = self._normalize_text(title)

        if "/terrain/" in lowered_href or " terrain " in f" {lowered_title} ":
            return "terrain"
        if "/appartement/" in lowered_href or "appartement" in lowered_title or "apartment" in lowered_title:
            return "appartement"
        if "/maison/" in lowered_href or "maison" in lowered_title or "villa" in lowered_title or "house" in lowered_title:
            return "maison"
        return None

    def _resolve_property_type(self, *, href: str, title: str | None) -> str | None:
        if self.url_kind == "land":
            return "terrain"
        return self._extract_property_type(href=href, title=title)

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
