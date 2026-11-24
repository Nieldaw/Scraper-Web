"""Extraction de l'image principale d'une carte d'annonce (HTML déjà en cache)."""

from urllib.parse import urljoin

from immo_ne_collector.services.images import valid_http_url

_IMG_ATTRS = ("src", "data-src", "data-lazy-src", "data-original")
_SRCSET_ATTRS = ("srcset", "data-srcset")
_SKIP_MARKERS = ("placeholder", "blank.", "spacer", "pixel", "logo", "sprite")


def extract_card_image_url(card, base_url: str) -> str | None:
    """Première image http(s) exploitable de la carte, ou None.

    Ignore les data: URI, les pixels/placeholders et les URL non http(s).
    """
    for img in card.select("img"):
        candidates = [img.get(attr) for attr in _IMG_ATTRS]
        for attr in _SRCSET_ATTRS:
            srcset = img.get(attr)
            if isinstance(srcset, str) and srcset.strip():
                candidates.append(srcset.split(",")[0].strip().split(" ")[0])
        for candidate in candidates:
            if not isinstance(candidate, str) or candidate.strip().startswith("data:"):
                continue
            url = (
                valid_http_url(urljoin(base_url, candidate.strip())) if candidate.strip() else None
            )
            if url and not any(marker in url.lower() for marker in _SKIP_MARKERS):
                return url
    return None
