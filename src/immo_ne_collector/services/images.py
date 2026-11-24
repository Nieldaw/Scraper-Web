"""Extraction et validation d'URL d'images (sans dépendance DB ni scraper)."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

_IMAGE_KEYS = ("image_url", "image", "photo_url", "photo", "thumbnail_url", "thumbnail", "img")
_IMAGE_LIST_KEYS = ("images", "image_urls", "photos", "photo_urls")


def valid_http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 2048:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return candidate


def extract_image_url(raw_data: Mapping[str, Any] | None) -> str | None:
    """Première URL d'image http(s) valide dans raw_data, sinon None (-> placeholder)."""
    if not isinstance(raw_data, Mapping):
        return None
    for key in _IMAGE_KEYS:
        value = raw_data.get(key)
        if isinstance(value, Mapping):
            value = value.get("url")
        url = valid_http_url(value)
        if url:
            return url
    for key in _IMAGE_LIST_KEYS:
        values = raw_data.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, Mapping):
                item = item.get("url")
            url = valid_http_url(item)
            if url:
                return url
    return None
