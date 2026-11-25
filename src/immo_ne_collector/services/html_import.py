"""Import manuel d'une page HTML enregistrée depuis le navigateur (Homegate, ImmoScout24, …).

Le fichier est conservé dans `data/cache/html/`, analysé par le parseur de la source choisie,
puis les annonces sont filtrées (vente, canton) et enregistrées en base.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from immo_ne_collector.scrapers.anibis import AnibisCachedHtmlScraper
from immo_ne_collector.scrapers.base import BaseScraper
from immo_ne_collector.scrapers.homegate import HomegateCachedHtmlScraper
from immo_ne_collector.scrapers.immoscout import ImmoscoutCachedHtmlScraper
from immo_ne_collector.scrapers.lookmove import LookmoveCachedHtmlScraper
from immo_ne_collector.services.anibis_filters import filter_collection_batch
from immo_ne_collector.services.collection import collect_and_normalize
from immo_ne_collector.services.persistence import persist_collection_batch
from immo_ne_collector.services.source_config import ROMANDY_CANTONS

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
IMPORT_SOURCES: dict[str, str] = {
    "homegate": "Homegate",
    "immoscout": "ImmoScout24",
    "anibis": "Anibis",
    "lookmove": "Lookmove",
}
CACHE_DIR = Path("data/cache/html")


class HtmlImportError(ValueError):
    """Erreur lisible par l'utilisateur."""


@dataclass(frozen=True)
class HtmlImportResult:
    source: str
    detected: int
    kept: int
    created: int
    updated: int
    unchanged: int
    saved_as: str


def _scraper_for(source: str, path: Path) -> BaseScraper:
    name = f"{source}_manual"
    if source == "homegate":
        return HomegateCachedHtmlScraper(html_path=path, source=name)
    if source == "immoscout":
        return ImmoscoutCachedHtmlScraper(html_path=path, source=name)
    if source == "anibis":
        return AnibisCachedHtmlScraper(html_path=path, source=name)
    return LookmoveCachedHtmlScraper(html_path=path, source=name)


def validate_upload(source: str, canton: str, content: bytes) -> str | None:
    """Retourne le canton de filtre (None = toute la Romandie) ou lève HtmlImportError."""
    if source not in IMPORT_SOURCES:
        raise HtmlImportError("Source inconnue.")
    if canton not in ("", "all", *ROMANDY_CANTONS):
        raise HtmlImportError("Canton inconnu.")
    if not content.strip():
        raise HtmlImportError("Le fichier est vide.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HtmlImportError("Le fichier dépasse 15 Mo.")
    head = content[:2000].lower()
    if b"<html" not in head and b"<!doctype" not in head and b"<body" not in content[:20000].lower():
        raise HtmlImportError("Ce fichier ne ressemble pas à une page HTML.")
    return None if canton in ("", "all") else canton


async def import_html_page(
    *, source: str, canton: str, content: bytes, cache_dir: Path = CACHE_DIR
) -> HtmlImportResult:
    canton_filter = validate_upload(source, canton, content)
    cache_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = cache_dir / f"manual_{source}_{stamp}.html"
    path.write_bytes(content)

    try:
        batch = await collect_and_normalize(_scraper_for(source, path))
    except Exception as exc:  # parseurs : erreurs spécifiques par source
        raise HtmlImportError(f"Lecture impossible de la page {IMPORT_SOURCES[source]} : {exc}") from exc
    if batch.collected_count == 0:
        raise HtmlImportError(
            "Aucune annonce trouvée dans cette page. Enregistrez la page de résultats complète "
            "(Ctrl+S, « Page web, complète ») une fois les annonces affichées."
        )
    filtered, stats = filter_collection_batch(
        batch, max_listings=None, transaction_type="sale", canton=canton_filter
    )
    result = await persist_collection_batch(filtered)
    return HtmlImportResult(
        source=source,
        detected=stats.detected_total,
        kept=len(filtered.listings),
        created=result.created_count,
        updated=result.updated_count,
        unchanged=result.unchanged_count,
        saved_as=path.name,
    )
