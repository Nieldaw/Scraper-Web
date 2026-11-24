"""Transforme le résultat d'une collecte en diagnostics lisibles (page /runs)."""

from typing import Any

MAX_TEXT = 500
MAX_ITEMS = 20

SOURCE_LABELS = {
    "anibis": "Anibis",
    "lookmove": "Lookmove",
    "homegate": "Homegate",
    "immoscout": "ImmoScout24",
}

_BLOCK_HINT = (
    "Le site refuse les requêtes automatisées. Le projet ne contourne pas ce blocage "
    "(règle anti-bot) : réessayez plus tard, ou analysez du HTML déjà en cache."
)


def _trunc(value: object) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def explain_stop_reason(source: str, reason: str) -> tuple[str, str | None]:
    """(message, conseil) pour un motif d'arrêt de pagination (ex. HTTP_403)."""
    label = SOURCE_LABELS.get(source, source)
    code = reason.upper()
    if code == "HTTP_403":
        return f"{label} a refusé l'accès (HTTP 403).", _BLOCK_HINT
    if code == "HTTP_429":
        return (
            f"{label} limite le débit (HTTP 429, trop de requêtes).",
            "Augmentez le délai ou réduisez le nombre de pages, puis réessayez plus tard.",
        )
    if code.startswith("HTTP_5"):
        return (
            f"{label} a renvoyé une erreur serveur ({code.replace('_', ' ')}).",
            "Problème côté site : réessayez plus tard.",
        )
    if code == "TIMEOUT":
        return f"{label} n'a pas répondu à temps (timeout).", "Réessayez, ou augmentez le timeout."
    return f"Collecte interrompue sur {label} : {reason}.", None


def _issue(level: str, message: str, hint: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"level": level, "message": _trunc(message)}
    if hint:
        item["hint"] = _trunc(hint)
    return item


def build_source_detail(canton: str, summary: Any) -> dict[str, Any]:
    """Résumé JSON-sérialisable d'une source/canton (attributs de SourceSummary)."""
    issues: list[dict[str, Any]] = []
    status = summary.source_status
    reason = summary.pagination_stopped_reason
    if reason:
        message, hint = explain_stop_reason(summary.source, reason)
        issues.append(_issue("error" if status == "FAIL" else "warning", message, hint))
    for error in summary.errors:
        issues.append(_issue("error", error))
    notes: list[str] = []
    for note in summary.notes:
        if note.startswith("WARNING:"):
            issues.append(_issue("warning", note.removeprefix("WARNING:").strip()))
        else:
            notes.append(_trunc(note))
    if status in {"WARNING", "FAIL"} and not issues:
        issues.append(_issue("warning", f"Statut {status} sans détail fourni par la source."))
    return {
        "canton": canton,
        "source": summary.source,
        "status": status,
        "pages_requested": summary.requested_pages,
        "pages_fetched": summary.fetched_pages,
        "pages_from_cache": summary.loaded_from_cache_pages,
        "detected": summary.detected_total,
        "kept": summary.kept_canton_count,
        "collected": summary.collected_count,
        "created": summary.created_count,
        "updated": summary.updated_count,
        "unchanged": summary.unchanged_count,
        "issues": issues[:MAX_ITEMS],
        "notes": notes[:MAX_ITEMS],
    }


def overall_status(*, fatal: bool, failures: int, warnings: int, export_errors: int) -> str:
    if fatal:
        return "FAILED"
    if failures or export_errors:
        return "PARTIAL"
    if warnings:
        return "WARNING"
    return "SUCCESS"


def top_level_runs(runs: list[Any]) -> list[Any]:
    """Retire les runs « techniques » imbriqués dans un job de collecte.

    La couche de persistance crée sa propre ligne `daily_runs` pour chaque lot de pages ; le job
    (`daily_collect`) en crée une autre qui englobe toute l'exécution. On ne garde que cette
    dernière : un run terminé est masqué s'il a démarré dans la fenêtre d'un job terminé.
    """
    jobs = [r for r in runs if (r.stats or {}).get("cantons") and r.finished_at is not None]

    def nested(run: Any) -> bool:
        if (run.stats or {}).get("cantons"):
            return False
        return any(job.started_at <= run.started_at <= job.finished_at for job in jobs)

    return [r for r in runs if not nested(r)]
