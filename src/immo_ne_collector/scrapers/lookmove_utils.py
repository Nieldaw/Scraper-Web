import hashlib
import re
import unicodedata
from urllib.parse import urlparse

CITY_BY_SLUG: dict[str, str] = {
    "neuchatel": "Neuchâtel",
    "la-chaux-de-fonds": "La Chaux-de-Fonds",
    "chaux-de-fonds": "La Chaux-de-Fonds",
    "le-locle": "Le Locle",
    "locle": "Le Locle",
    "cortaillod": "Cortaillod",
    "le-landeron": "Le Landeron",
    "st-blaise": "St-Blaise",
    "saint-blaise": "Saint-Blaise",
    "hauterive-ne": "Hauterive NE",
    "peseux": "Peseux",
    "boudry": "Boudry",
    "colombier-ne": "Colombier NE",
    "fontaines-ne": "Fontaines NE",
    "savagnier": "Savagnier",
    "thielle": "Thielle",
    "cernier": "Cernier",
    "les-ponts-de-martel": "Les Ponts-de-Martel",
    "lignieres": "Lignières",
    "noiraigue": "Noiraigue",
    "bole": "Bôle",
}

POSTAL_BY_CITY: dict[str, str] = {
    "Neuchâtel": "2000",
    "La Chaux-de-Fonds": "2300",
    "Le Locle": "2400",
    "Cortaillod": "2016",
    "Le Landeron": "2525",
    "St-Blaise": "2072",
    "Saint-Blaise": "2072",
    "Hauterive NE": "2068",
    "Peseux": "2034",
    "Boudry": "2017",
    "Colombier NE": "2013",
    "Fontaines NE": "2046",
    "Savagnier": "2065",
    "Thielle": "2075",
    "Cernier": "2053",
    "Les Ponts-de-Martel": "2316",
}


def normalize_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = text.replace("à", "a")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def derive_stable_id_from_url(url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"url_{digest}"


def extract_lookmove_listing_id(url_or_path: str) -> str | None:
    if not url_or_path:
        return None
    parsed = urlparse(url_or_path)
    target = parsed.path or url_or_path
    # Typical numeric id in path, often near end of listing URL.
    match = re.search(r"/(\d{5,})(?:[/?#]|$)", target)
    if match:
        return match.group(1)
    # Lookmove URLs often embed id after a comma suffix.
    match = re.search(r",(\d{5,})(?:[/?#]|$)", target)
    if match:
        return match.group(1)
    # Fallback: id-like query params if present.
    match = re.search(r"(?:id|listingId|itemId)=(\d{5,})", url_or_path, flags=re.IGNORECASE)
    return match.group(1) if match else None


def classify_transaction_type(
    *,
    href: str,
    title: str | None,
    description: str | None,
    card_text: str,
    page_context: str,
) -> str:
    combined = normalize_text(" ".join(part for part in [href, title or "", description or "", card_text] if part))

    rent_keywords = (
        "location",
        "a louer",
        "louer",
        "sous-louer",
        "sous louer",
        "sous-location",
        "sous location",
        "loyer",
        "par mois",
        "/mois",
        "mois.",
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


def detect_page_transaction_context(text: str) -> str:
    normalized = normalize_text(text)
    has_buy = any(word in normalized for word in ("acheter", "buy", "kaufen", "acquistare"))
    has_rent = any(word in normalized for word in ("louer", "rent", "mieten", "affitt"))

    if has_buy and not has_rent:
        return "sale"
    if has_rent and not has_buy:
        return "rent"
    return "unknown"


def infer_property_type_from_href(href: str) -> str | None:
    lowered = normalize_text(href)
    if "appartement" in lowered or "apartment" in lowered:
        return "appartement"
    if "maison" in lowered or "house" in lowered or "villa" in lowered:
        return "maison"
    return None


def infer_city_from_href(href: str) -> str | None:
    parsed = urlparse(href)
    path = parsed.path.strip("/")
    match = re.search(r"-dans-([^,/]+)", path)
    if not match:
        return None
    slug = normalize_text(match.group(1))
    if slug in CITY_BY_SLUG:
        return CITY_BY_SLUG[slug]

    for prefix in ("la-", "le-", "les-", "l-"):
        if slug.startswith(prefix):
            stripped = slug[len(prefix) :]
            if stripped in CITY_BY_SLUG:
                return CITY_BY_SLUG[stripped]

    return None


def infer_postal_code_from_city(city: str | None) -> str | None:
    if city is None:
        return None
    return POSTAL_BY_CITY.get(city)


def infer_title_from_href(href: str) -> str | None:
    parsed = urlparse(href)
    segment = parsed.path.rsplit("/", 1)[-1].split(",", 1)[0]
    if not segment:
        return None

    ptype = infer_property_type_from_href(href)
    city = infer_city_from_href(href)
    if ptype and city:
        return f"{ptype.capitalize()} à vendre à {city}"

    cleaned = segment.replace("-", " ").strip()
    if not cleaned:
        return None
    return cleaned[0].upper() + cleaned[1:]
