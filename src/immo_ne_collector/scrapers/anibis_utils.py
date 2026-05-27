import unicodedata

NE_CITY_KEYWORDS = (
    "neuchatel",
    "la chaux-de-fonds",
    "chaux-de-fonds",
    "le locle",
    "val-de-travers",
    "couvet",
    "colombier",
    "cernier",
    "peseux",
    "marin-epagnier",
    "st-blaise",
    "saint-blaise",
    "le landeron",
    "travers",
    "corcelles",
    "boudry",
    "cortaillod",
)


def normalize_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def is_canton_ne_listing(url: str, city: str | None, postal_code: str | None) -> bool:
    normalized_url = normalize_text(url)
    normalized_city = normalize_text(city)

    if "/neuchatel/" in normalized_url:
        return True

    if "/berne/" in normalized_url or "/bern/" in normalized_url:
        return False

    if normalized_city.endswith(" ne"):
        return True

    if normalized_city and any(keyword in normalized_city for keyword in NE_CITY_KEYWORDS):
        return True

    if postal_code and postal_code.isdigit():
        code = int(postal_code)
        if 2000 <= code <= 2999:
            return True

    return False
