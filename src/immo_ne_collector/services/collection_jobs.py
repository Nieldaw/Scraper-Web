"""Lancement d'une collecte en arrière-plan depuis l'interface web.

La collecte tourne dans un *sous-processus* (`python -m immo_ne_collector.jobs.daily_collect`)
pour ne pas bloquer le serveur web. Les arguments sont validés puis passés en liste (pas de
shell). Une seule collecte à la fois.
"""

import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.models import DailyRun
from immo_ne_collector.services.source_config import ROMANDY_CANTONS

ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = ROOT / "data" / "logs"

# Sources activables depuis l'interface. Homegate/ImmoScout restent désactivées (anti-bot).
ENABLED_SOURCES: dict[str, str] = {"anibis": "Anibis", "lookmove": "Lookmove"}
DISABLED_SOURCES: dict[str, str] = {
    "homegate": "Homegate — désactivé (protection anti-bot, HTML en cache uniquement)",
    "immoscout": "ImmoScout24 — désactivé (protection anti-bot, HTML en cache uniquement)",
}
MAX_PAGES_UI = 5
MAX_LISTINGS_UI = 500
MAX_DETAILS_UI = 100
STALE_AFTER = timedelta(hours=2)
LOG_TAIL_CHARS = 1500

_process: asyncio.subprocess.Process | None = None
_watchers: set[asyncio.Task] = set()


class CollectionBusyError(RuntimeError):
    pass


@dataclass(frozen=True)
class CollectionRequest:
    sources: list[str]
    cantons: list[str]
    max_pages: int = 1
    max_listings: int | None = None
    enrich_details: bool = True
    max_details: int = 30


def _parse_int(value: str | None, *, label: str, minimum: int, maximum: int) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        number = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label} : nombre entier attendu.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} : valeur comprise entre {minimum} et {maximum} attendue.")
    return number


def validate_request(
    *,
    sources: list[str],
    cantons: list[str],
    max_pages: str | None,
    max_listings: str | None,
    enrich_details: bool,
    max_details: str | None,
) -> CollectionRequest:
    """Valide les valeurs du formulaire. Lève ValueError (message affichable en français)."""
    chosen_sources = [s for s in dict.fromkeys(x.strip().lower() for x in sources) if s]
    if not chosen_sources:
        raise ValueError("Choisissez au moins une source.")
    unknown = [s for s in chosen_sources if s not in ENABLED_SOURCES]
    if unknown:
        raise ValueError(f"Source non disponible : {', '.join(unknown)}.")

    chosen_cantons = [c for c in dict.fromkeys(x.strip().upper() for x in cantons) if c]
    if not chosen_cantons:
        raise ValueError("Choisissez au moins un canton.")
    bad = [c for c in chosen_cantons if c not in ROMANDY_CANTONS]
    if bad:
        raise ValueError(
            f"Canton inconnu : {', '.join(bad)} (valeurs acceptées : {', '.join(ROMANDY_CANTONS)})."
        )

    return CollectionRequest(
        sources=chosen_sources,
        cantons=chosen_cantons,
        max_pages=_parse_int(max_pages, label="Pages", minimum=1, maximum=MAX_PAGES_UI) or 1,
        max_listings=_parse_int(
            max_listings, label="Annonces max", minimum=1, maximum=MAX_LISTINGS_UI
        ),
        enrich_details=enrich_details,
        max_details=_parse_int(max_details, label="Fiches max", minimum=1, maximum=MAX_DETAILS_UI)
        or 30,
    )


def build_argv(request: CollectionRequest) -> list[str]:
    argv = [
        sys.executable,
        "-m",
        "immo_ne_collector.jobs.daily_collect",
        "--canton",
        ",".join(request.cantons),
        "--sources",
        ",".join(request.sources),
        "--max-pages",
        str(request.max_pages),
        "--max-details",
        str(request.max_details),
    ]
    if request.max_listings is not None:
        argv += ["--max-listings", str(request.max_listings)]
    if not request.enrich_details:
        argv.append("--no-enrich-details")
    return argv


async def running_collection(session: AsyncSession) -> DailyRun | None:
    """Collecte en cours (RUNNING, démarrée il y a moins de 2 h), sinon None."""
    since = datetime.now(UTC) - STALE_AFTER
    result = await session.execute(
        select(DailyRun)
        .where(DailyRun.status == "RUNNING", DailyRun.started_at >= since)
        .order_by(DailyRun.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _tail(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(journal illisible)"
    return text[-LOG_TAIL_CHARS:].strip() or "(aucune sortie)"


async def _watch(
    process: asyncio.subprocess.Process, log_path: Path, launched_at: datetime
) -> None:
    """Si le sous-processus échoue sans avoir enregistré de run, on le consigne en base."""
    global _process
    code = await process.wait()
    if _process is process:
        _process = None
    if code == 0:
        return
    message = f"Le processus de collecte s'est terminé avec le code {code}.\n{_tail(log_path)}"
    async with AsyncSessionLocal() as session:
        run = (
            await session.execute(
                select(DailyRun)
                .where(DailyRun.started_at >= launched_at - timedelta(seconds=5))
                .order_by(DailyRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if run is None:
            run = DailyRun(started_at=launched_at, stats={})
            session.add(run)
        elif run.status != "RUNNING":
            return  # le job a lui-même consigné son résultat (PARTIAL, FAILED…) avec ses détails
        run.status = "FAILED"
        run.finished_at = datetime.now(UTC)
        run.error = f"{message}\nJournal : {log_path.relative_to(ROOT)}"
        await session.commit()


async def launch_collection(request: CollectionRequest) -> Path:
    """Démarre la collecte. Retourne le chemin du journal. Lève CollectionBusyError."""
    global _process
    if _process is not None and _process.returncode is None:
        raise CollectionBusyError("Une collecte est déjà en cours de démarrage ou d'exécution.")
    async with AsyncSessionLocal() as session:
        if await running_collection(session) is not None:
            raise CollectionBusyError("Une collecte est déjà en cours.")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    launched_at = datetime.now(UTC)
    log_path = LOG_DIR / f"collect_{launched_at.strftime('%Y%m%dT%H%M%SZ')}.log"
    with log_path.open("wb") as log_file:
        process = await asyncio.create_subprocess_exec(
            *build_argv(request),
            cwd=ROOT,
            stdout=log_file,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
        )
    _process = process
    task = asyncio.create_task(_watch(process, log_path, launched_at))
    _watchers.add(task)
    task.add_done_callback(_watchers.discard)
    return log_path
