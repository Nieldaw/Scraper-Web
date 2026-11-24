import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from immo_ne_collector.db import AsyncSessionLocal
from immo_ne_collector.main import app
from immo_ne_collector.models import DailyRun
from immo_ne_collector.services import collection_jobs
from immo_ne_collector.services.collection_jobs import (
    CollectionRequest,
    build_argv,
    validate_request,
)
from immo_ne_collector.services.run_diagnostics import (
    build_source_detail,
    explain_stop_reason,
    overall_status,
)


@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def _valid(**over):
    base = dict(
        sources=["anibis"],
        cantons=["ne"],
        max_pages="2",
        max_listings="",
        enrich_details=True,
        max_details="",
    )
    base.update(over)
    return base


# --- validation / argv ---------------------------------------------------------------


def test_validate_request_normalizes_values():
    req = validate_request(**_valid(sources=["Anibis", "anibis", "lookmove"], cantons=["ne", "VD"]))
    assert req.sources == ["anibis", "lookmove"] and req.cantons == ["NE", "VD"]
    assert req.max_pages == 2 and req.max_listings is None and req.max_details == 30


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"sources": []}, "au moins une source"),
        ({"sources": ["homegate"]}, "non disponible"),
        ({"sources": ["x; rm -rf /"]}, "non disponible"),
        ({"cantons": []}, "au moins un canton"),
        ({"cantons": ["XX"]}, "Canton inconnu"),
        ({"max_pages": "0"}, "Pages"),
        ({"max_pages": "99"}, "Pages"),
        ({"max_pages": "abc"}, "entier"),
        ({"max_listings": "-3"}, "Annonces max"),
    ],
)
def test_validate_request_rejects_bad_input(override, fragment):
    with pytest.raises(ValueError, match=fragment):
        validate_request(**_valid(**override))


def test_build_argv_is_a_plain_list():
    argv = build_argv(
        CollectionRequest(
            sources=["anibis", "lookmove"],
            cantons=["NE", "VD"],
            max_pages=2,
            max_listings=10,
            enrich_details=False,
            max_details=5,
        )
    )
    assert argv[1:4] == ["-m", "immo_ne_collector.jobs.daily_collect", "--canton"]
    assert "NE,VD" in argv and "anibis,lookmove" in argv
    assert "--no-enrich-details" in argv and argv[argv.index("--max-listings") + 1] == "10"


def test_collector_script_accepts_canton_list():
    spec = importlib.util.spec_from_file_location(
        "collect_script", "scripts/collect_sale_by_canton.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = module._build_parser().parse_args(["--canton", "ne, VD,ne"])
    assert module._resolve_cantons(args) == ["NE", "VD"]
    with pytest.raises(ValueError):
        module._resolve_cantons(module._build_parser().parse_args(["--canton", "NE,XX"]))


# --- diagnostics ---------------------------------------------------------------------


def test_explain_403_mentions_block_and_no_circumvention():
    message, hint = explain_stop_reason("lookmove", "HTTP_403")
    assert "Lookmove" in message and "403" in message
    assert "ne contourne pas" in hint


def test_build_source_detail_and_status():
    summary = SimpleNamespace(
        source="lookmove",
        source_status="WARNING",
        pagination_stopped_reason="HTTP_403",
        errors=[],
        notes=["Lookmove blocked at page 1", "WARNING: autre souci"],
        requested_pages=1,
        fetched_pages=0,
        loaded_from_cache_pages=0,
        detected_total=0,
        kept_canton_count=0,
        collected_count=0,
        created_count=0,
        updated_count=0,
        unchanged_count=0,
    )
    detail = build_source_detail("NE", summary)
    levels = [i["level"] for i in detail["issues"]]
    assert levels == ["warning", "warning"] and "403" in detail["issues"][0]["message"]
    assert detail["notes"] == ["Lookmove blocked at page 1"]
    assert overall_status(fatal=False, failures=0, warnings=1, export_errors=0) == "WARNING"
    assert overall_status(fatal=False, failures=1, warnings=1, export_errors=0) == "PARTIAL"
    assert overall_status(fatal=True, failures=0, warnings=0, export_errors=0) == "FAILED"


# --- pages ---------------------------------------------------------------------------


@pytest.mark.db
async def test_settings_form_renders(client):
    r = await client.get("/settings")
    assert r.status_code == 200
    for expected in ("Anibis", "Lookmove", "Lancer la collecte", 'value="NE"', "désactivé"):
        assert expected in r.text


@pytest.mark.db
async def test_settings_post_validation_error_keeps_values(client):
    r = await client.post("/settings", data={"cantons": ["NE"], "max_pages": "3"})
    assert r.status_code == 422
    assert "au moins une source" in r.text and 'value="3"' in r.text


@pytest.mark.db
async def test_settings_post_launches_in_background(client, monkeypatch):
    seen = []

    async def fake_launch(req):
        seen.append(req)
        return Path("data/logs/x.log")

    monkeypatch.setattr("immo_ne_collector.web.routes.launch_collection", fake_launch)
    r = await client.post(
        "/settings",
        data={
            "sources": ["anibis", "lookmove"],
            "cantons": ["NE", "VD"],
            "max_pages": "2",
            "max_listings": "5",
            "enrich_details": "on",
            "max_details": "7",
        },
    )
    assert r.status_code == 303 and r.headers["location"] == "/runs?launched=1"
    assert seen[0].cantons == ["NE", "VD"] and seen[0].max_details == 7 and seen[0].enrich_details


@pytest.mark.db
async def test_settings_post_busy(client, monkeypatch):
    async def busy(req):
        raise collection_jobs.CollectionBusyError("Une collecte est déjà en cours.")

    monkeypatch.setattr("immo_ne_collector.web.routes.launch_collection", busy)
    r = await client.post("/settings", data={"sources": ["anibis"], "cantons": ["NE"]})
    assert r.status_code == 422 and "déjà en cours" in r.text


@pytest.mark.db
async def test_runs_page_shows_actionable_errors(client):
    stats = {
        "cantons": ["NE"],
        "sources": ["anibis", "lookmove"],
        "collected": 10,
        "created": 10,
        "updated": 0,
        "unchanged": 0,
        "details": [
            {
                "canton": "NE",
                "source": "lookmove",
                "status": "WARNING",
                "pages_requested": 1,
                "pages_fetched": 0,
                "pages_from_cache": 0,
                "detected": 0,
                "kept": 0,
                "collected": 0,
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "notes": ["technique <b>x</b>"],
                "issues": [
                    {
                        "level": "warning",
                        "message": "Lookmove a refusé l'accès (HTTP 403).",
                        "hint": "Le projet ne contourne pas ce blocage",
                    }
                ],
            },
        ],
    }
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        session.add(
            DailyRun(
                started_at=now,
                finished_at=now + timedelta(seconds=75),
                status="WARNING",
                stats=stats,
            )
        )
        session.add(
            DailyRun(
                started_at=now - timedelta(days=1),
                status="FAILED",
                stats={},
                error="Boom <script>alert(1)</script>",
            )
        )
        await session.commit()
    page = (await client.get("/runs")).text
    assert "Lookmove a refusé l&#39;accès (HTTP 403)" in page or "Lookmove a refusé l'accès" in page
    assert "ne contourne pas ce blocage" in page and "1 min 15 s" in page
    assert "1 avertissement" in page and "Avertissements" in page
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page  # échappé
    assert "technique &lt;b&gt;x&lt;/b&gt;" in page
    assert "Échec" in page and "Boom" in page


@pytest.mark.db
async def test_running_collection_detection_and_stale_ignored():
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        session.add(DailyRun(started_at=now - timedelta(hours=5), status="RUNNING", stats={}))
        await session.commit()
        assert await collection_jobs.running_collection(session) is None
        session.add(DailyRun(started_at=now, status="RUNNING", stats={}))
        await session.commit()
        assert await collection_jobs.running_collection(session) is not None


@pytest.mark.db
async def test_watcher_records_crash_without_run(tmp_path, monkeypatch):
    monkeypatch.setattr(collection_jobs, "ROOT", tmp_path)
    log = tmp_path / "x.log"
    log.write_text("usage: ... error: bad arg", encoding="utf-8")

    class FakeProc:
        returncode = 2

        async def wait(self):
            return 2

    await collection_jobs._watch(FakeProc(), log, datetime.now(UTC))
    async with AsyncSessionLocal() as session:
        run = (await session.execute(__import__("sqlalchemy").select(DailyRun))).scalar_one()
    assert run.status == "FAILED" and "code 2" in run.error and "bad arg" in run.error


@pytest.mark.db
async def test_watcher_marks_hung_running_row_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(collection_jobs, "ROOT", tmp_path)
    log = tmp_path / "x.log"
    log.write_text("Traceback...", encoding="utf-8")
    started = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        session.add(DailyRun(started_at=started, status="RUNNING", stats={}))
        await session.commit()

    class FakeProc:
        returncode = 1

        async def wait(self):
            await asyncio.sleep(0)
            return 1

    await collection_jobs._watch(FakeProc(), log, started)
    async with AsyncSessionLocal() as session:
        run = (await session.execute(__import__("sqlalchemy").select(DailyRun))).scalar_one()
    assert run.status == "FAILED" and run.finished_at is not None


@pytest.mark.db
async def test_runs_page_hides_persistence_rows_nested_in_a_job(client):
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        session.add(  # le job englobant
            DailyRun(
                started_at=now - timedelta(minutes=2),
                finished_at=now,
                status="WARNING",
                stats={
                    "cantons": ["NE"],
                    "sources": ["anibis"],
                    "collected": 3,
                    "created": 3,
                    "updated": 0,
                    "unchanged": 0,
                    "details": [],
                },
            )
        )
        session.add(  # ligne technique créée par la persistance pendant le job
            DailyRun(
                started_at=now - timedelta(minutes=1),
                finished_at=now,
                status="SUCCESS",
                stats={"source": "anibis_cached", "collected_count": 3},
            )
        )
        session.add(  # run indépendant (script lancé à la main), hors fenêtre
            DailyRun(
                started_at=now - timedelta(days=2),
                finished_at=now - timedelta(days=2),
                status="SUCCESS",
                stats={"source": "anibis_cached", "collected_count": 1},
            )
        )
        await session.commit()
    page = (await client.get("/runs")).text
    assert page.count('class="run"') == 2  # job + run indépendant ; la ligne imbriquée est masquée
    assert "Avertissements" in page
    assert "Avertissements" in (await client.get("/")).text  # tableau de bord : même logique
