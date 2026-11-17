import hashlib
import re
import unicodedata
from urllib.parse import urlparse

CITY_BY_SLUG: dict[str, str] = {
    # Neuchâtel (NE)
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
    # Genève (GE)
    "geneve": "Genève",
    "carouge": "Carouge",
    "meyrin": "Meyrin",
    "vernier": "Vernier",
    "onex": "Onex",
    "lancy": "Lancy",
    "versoix": "Versoix",
    # Vaud (VD)
    "lausanne": "Lausanne",
    "nyon": "Nyon",
    "morges": "Morges",
    "vevey": "Vevey",
    "yverdon": "Yverdon",
    "renens": "Renens",
    "pully": "Pully",
    "montreux": "Montreux",
    "montagny-pres-yverdon": "Montagny-près-Yverdon",
    # Jura (JU)
    "delemont": "Délémont",
    "delémont": "Délémont",
    "porrentruy": "Porrentruy",
    "saignelegier": "Saignelégier",
    "courgenay": "Courgenay",
    "courrendlin": "Courrendlin",
    "bassecourt": "Bassecourt",
    # Fribourg (FR)
    "fribourg": "Fribourg",
    "bulle": "Bulle",
    "romont": "Romont",
    "murten": "Morat",
    "morat": "Morat",
    "villars-sur-glane": "Villars-sur-Glâne",
    "estavayer": "Estavayer",
    # Valais (VS)
    "sion": "Sion",
    "sierre": "Sierre",
    "martigny": "Martigny",
    "monthey": "Monthey",
    "verbier": "Verbier",
    "crans-montana": "Crans-Montana",
    "visp": "Visp",
    "brig": "Brig",
}

POSTAL_BY_CITY: dict[str, str] = {
    # Neuchâtel (NE)
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
    # Genève (GE)
    "Genève": "1200",
    "Carouge": "1227",
    "Meyrin": "1217",
    "Vernier": "1214",
    "Onex": "1213",
    "Lancy": "1212",
    "Versoix": "1290",
    # Vaud (VD)
    "Lausanne": "1000",
    "Nyon": "1260",
    "Morges": "1110",
    "Vevey": "1800",
    "Yverdon": "1400",
    "Renens": "1020",
    "Pully": "1009",
    "Montreux": "1820",
    "Montagny-près-Yverdon": "1424",
    # Jura (JU)
    "Délémont": "2800",
    "Porrentruy": "2900",
    "Saignelégier": "2350",
    "Courgenay": "2932",
    "Courrendlin": "2900",
    "Bassecourt": "2854",
    # Fribourg (FR)
    "Fribourg": "1700",
    "Bulle": "1630",
    "Romont": "1680",
    "Morat": "3280",
    "Villars-sur-Glâne": "1752",
    "Estavayer": "1470",
    # Valais (VS)
    "Sion": "1950",
    "Sierre": "3960",
    "Martigny": "1920",
    "Monthey": "1870",
    "Verbier": "1936",
    "Crans-Montana": "3963",
    "Visp": "3930",
    "Brig": "3900",
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
