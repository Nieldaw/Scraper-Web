"""Lecture d'une page de détail Anibis (bloc __NEXT_DATA__).

Pourquoi : les valeurs de la page de *résultats* (prix, titre, pièces) ne sont pas fiables
(ex. 1 052 727.- affiché vs 890 000.- sur la fiche). La fiche expose des attributs structurés :
prix, pièces, surface, adresse.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
_ROOMS_IN_TEXT_RE = re.compile(r"(\d+(?:[.,]\d)?)\s*(?:pi[eè]ces?|pces?|p\b)", re.IGNORECASE)
# Types de bien dont « Surface » est la surface habitable (sinon : surface de parcelle).
_LIVING_AREA_PREFIXES = ("apartment", "house", "flat", "villa", "building")


class AnibisDetailParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnibisDetail:
    listing_id: str | None = None
    title: str | None = None
    description: str | None = None
    price_raw: str | None = None
    price_is_rent: bool = False
    rooms_raw: str | None = None
    living_area_raw: str | None = None
    plot_area_raw: str | None = None
    address_raw: str | None = None
    property_prefix: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def _find_listing_node(next_data: dict[str, Any]) -> dict[str, Any] | None:
    queries = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("dehydratedState", {})
        .get("queries", [])
    )
    for query in queries:
        data = (query.get("state") or {}).get("data")
        if isinstance(data, dict) and isinstance(data.get("listing"), dict):
            return data["listing"]
    return None


def parse_anibis_detail(html_text: str) -> AnibisDetail:
    match = _NEXT_DATA_RE.search(html_text)
    if match is None:
        raise AnibisDetailParseError("bloc __NEXT_DATA__ introuvable")
    try:
        listing = _find_listing_node(json.loads(match.group(1)))
    except json.JSONDecodeError as exc:
        raise AnibisDetailParseError(f"__NEXT_DATA__ illisible: {exc}") from exc
    if listing is None:
        raise AnibisDetailParseError("fiche annonce introuvable dans __NEXT_DATA__")

    localization = listing.get("localization") or {}
    title = localization.get("title")
    formatted_price = listing.get("formattedPrice")
    price_is_rent = isinstance(formatted_price, str) and "mois" in formatted_price.lower()
    has_digit = isinstance(formatted_price, str) and any(c.isdigit() for c in formatted_price)

    rooms_attr = size_attr = address = prefix = None
    for prop in listing.get("properties") or []:
        prop_id = str(prop.get("listingPropertyID") or "")
        text = prop.get("text")
        if prop_id.endswith("_realEstateRooms"):
            rooms_attr, prefix = text, prop_id.split("_", 1)[0]
        elif prop_id.endswith("_realEstateSize"):
            size_attr, prefix = text, prefix or prop_id.split("_", 1)[0]
        elif prop_id == "synthetic_address":
            address = text

    # L'attribut « pièces » est arrondi à l'entier (4 pour 4,5) : le titre est plus précis.
    rooms_raw = rooms_attr
    title_match = _ROOMS_IN_TEXT_RE.search(title or "")
    if title_match:
        rooms_raw = title_match.group(1)

    is_living = (prefix or "").lower() in _LIVING_AREA_PREFIXES
    return AnibisDetail(
        listing_id=listing.get("listingID"),
        title=title,
        description=localization.get("body"),
        price_raw=formatted_price if has_digit and not price_is_rent else None,
        price_is_rent=price_is_rent,
        rooms_raw=str(rooms_raw) if rooms_raw not in (None, "") else None,
        living_area_raw=str(size_attr) if size_attr and is_living else None,
        plot_area_raw=str(size_attr) if size_attr and not is_living else None,
        address_raw=address or None,
        property_prefix=prefix,
    )
