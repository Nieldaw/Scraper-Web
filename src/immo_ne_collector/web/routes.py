"""Pages HTML (Jinja2 + HTMX) : tableau de bord, propriétés, mandats."""

from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from immo_ne_collector.api.routes import mandate_create_to_criteria, property_to_out
from immo_ne_collector.db import get_session
from immo_ne_collector.models import DailyRun, Property
from immo_ne_collector.schemas import SearchMandateCreate
from immo_ne_collector.services.amenities import extract_amenities
from immo_ne_collector.services.images import extract_image_urls
from immo_ne_collector.services.property_history import (
    FIELD_LABELS,
    extract_agency_name,
    list_history,
)
from immo_ne_collector.services.html_import import (
    IMPORT_SOURCES,
    HtmlImportError,
    import_html_page,
)
from immo_ne_collector.services.collection_jobs import (
    DISABLED_SOURCES,
    ENABLED_SOURCES,
    MAX_DETAILS_UI,
    MAX_LISTINGS_UI,
    MAX_PAGES_UI,
    CollectionBusyError,
    launch_collection,
    running_collection,
    validate_request,
)
from immo_ne_collector.services.mandates import (
    apply_search_mandate,
    create_search_mandate,
    list_search_mandates,
)
from immo_ne_collector.services.property_queries import (
    MAX_PAGE_SIZE,
    SORTS,
    PropertyFilters,
    count_by_status,
    get_property,
    search_properties,
    sitn_status_label,
)
from immo_ne_collector.services.run_diagnostics import top_level_runs
from immo_ne_collector.services.source_config import ROMANDY_CANTONS

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter(include_in_schema=False)
SessionDep = Annotated[AsyncSession, Depends(get_session)]

STATUS_TABS = (
    ("all", "Tous"),
    ("new", "Nouveaux"),
    ("modified", "Modifiés"),
    ("inactive", "Inactifs"),
)
SOON_PAGES = {"analysis": "Analysis", "chat": "Chat", "account": "User & Account"}
PAGE_SIZE = 24


def _render(request: Request, name: str, active: str, *, status_code: int = 200, **context):
    return templates.TemplateResponse(
        request, name, {"active": active, **context}, status_code=status_code
    )


def _opt_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value.replace("'", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _csv_list(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: SessionDep):
    stats = await count_by_status(session)
    recent, _ = await search_properties(session, PropertyFilters(status="new"), page_size=8)
    recent_runs = (
        (await session.execute(select(DailyRun).order_by(DailyRun.started_at.desc()).limit(20)))
        .scalars()
        .all()
    )
    visible_runs = top_level_runs(list(recent_runs))
    last_run = visible_runs[0] if visible_runs else None
    return _render(
        request,
        "dashboard.html",
        "dashboard",
        stats=stats,
        recent=[property_to_out(r) for r in recent],
        last_run=last_run,
    )


@router.get("/properties", response_class=HTMLResponse)
async def properties_page(
    request: Request,
    session: SessionDep,
    q: str | None = None,
    status: Annotated[str, Query(pattern="^(all|new|modified|inactive)$")] = "all",
    city: str | None = None,
    canton: str | None = None,
    min_price: str | None = None,
    max_price: str | None = None,
    min_rooms: str | None = None,
    unprocessed: str | None = None,
    sort: Annotated[str, Query(pattern=f"^({'|'.join(SORTS)})$")] = "recent",
    page: Annotated[int, Query(ge=1)] = 1,
):
    filters = PropertyFilters(
        q=q,
        status=status,
        city=city,
        canton=canton,
        min_price=_opt_float(min_price),
        max_price=_opt_float(max_price),
        min_rooms=_opt_float(min_rooms),
        unprocessed=bool(unprocessed),
        sort=sort,
    )
    rows, total = await search_properties(session, filters, page=page, page_size=PAGE_SIZE)
    context = {
        "items": [property_to_out(r) for r in rows],
        "total": total,
        "page": page,
        "pages": max(1, -(-total // PAGE_SIZE)),
        "filters": {
            "q": q or "",
            "status": status,
            "city": city or "",
            "canton": canton or "",
            "min_price": min_price or "",
            "max_price": max_price or "",
            "min_rooms": min_rooms or "",
            "unprocessed": "1" if unprocessed else "",
            "sort": sort,
        },
        "status_tabs": STATUS_TABS,
    }
    context["qs"] = urlencode({k: v for k, v in context["filters"].items() if v})
    # Requête HTMX (filtre/pagination) : on ne renvoie que la grille.
    if request.headers.get("HX-Request") == "true" and request.headers.get("HX-Boosted") != "true":
        return _render(request, "_property_grid.html", "properties", **context)
    return _render(request, "properties.html", "properties", **context)


@router.get("/properties/{property_id}", response_class=HTMLResponse)
async def property_detail(property_id: UUID, request: Request, session: SessionDep):
    row = await get_property(session, property_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Bien introuvable")
    listings = sorted(row.listings, key=lambda item: item.last_seen_at, reverse=True)
    return _render(
        request,
        "property_detail.html",
        "properties",
        item=property_to_out(row),
        listings=listings,
        sitn_url=row.sitn_url,
        history=await list_history(session, property_id),
        description=next((l.description for l in listings if l.description and l.description.strip()), None),
        amenities=extract_amenities(row.title, *(l.description for l in listings)),
        gallery=extract_image_urls(row.raw_data) or [],
        agency=extract_agency_name(row.raw_data),
        sitn_label=sitn_status_label(row.sitn_status),
        map_query=", ".join(p for p in (row.postal_code, row.city) if p),
        listing_agencies={str(l.id): extract_agency_name(l.raw_data) for l in listings},
        field_labels=FIELD_LABELS,
    )


@router.post("/properties/{property_id}/processed")
async def toggle_processed(
    property_id: UUID, session: SessionDep, processed: Annotated[str, Form()] = "1"
):
    row = await get_property(session, property_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Bien introuvable")
    row.is_processed = processed == "1"
    await session.commit()
    return RedirectResponse(f"/properties/{property_id}", status_code=303)


@router.get("/mandates", response_class=HTMLResponse)
async def mandates_page(request: Request, session: SessionDep, selected: UUID | None = None):
    mandates = await list_search_mandates(session)
    selected_mandate = next((m for m in mandates if m.id == selected), None)
    matches: list | None = None
    matches_total = 0
    if selected_mandate is not None:
        result = await apply_search_mandate(session, mandate_id=selected_mandate.id)
        matches_total = len(result.matches)
        ids = [m.property_id for m in result.matches][:MAX_PAGE_SIZE]
        rows = (
            (await session.execute(select(Property).where(Property.id.in_(ids)))).scalars().all()
            if ids
            else []
        )
        order = {pid: i for i, pid in enumerate(ids)}
        matches = [property_to_out(r) for r in sorted(rows, key=lambda r: order[r.id])]
    return _render(
        request,
        "mandates.html",
        "mandates",
        mandates=mandates,
        selected=selected_mandate,
        matches=matches,
        matches_total=matches_total,
    )


@router.post("/mandates")
async def create_mandate_form(
    session: SessionDep,
    name: Annotated[str, Form()],
    cities: Annotated[str | None, Form()] = None,
    property_types: Annotated[str | None, Form()] = None,
    min_price_chf: Annotated[str | None, Form()] = None,
    max_price_chf: Annotated[str | None, Form()] = None,
    min_rooms: Annotated[str | None, Form()] = None,
    max_rooms: Annotated[str | None, Form()] = None,
    min_living_area_m2: Annotated[str | None, Form()] = None,
    max_living_area_m2: Annotated[str | None, Form()] = None,
    only_active: Annotated[str | None, Form()] = None,
):
    if not name.strip():
        raise HTTPException(status_code=422, detail="Le nom du mandat est obligatoire")
    payload = SearchMandateCreate(
        name=name.strip(),
        cities=_csv_list(cities),
        property_types=_csv_list(property_types),
        min_price_chf=_opt_float(min_price_chf),
        max_price_chf=_opt_float(max_price_chf),
        min_rooms=_opt_float(min_rooms),
        max_rooms=_opt_float(max_rooms),
        min_living_area_m2=_opt_float(min_living_area_m2),
        max_living_area_m2=_opt_float(max_living_area_m2),
        only_active=only_active is not None,
    )
    mandate = await create_search_mandate(session, criteria=mandate_create_to_criteria(payload))
    return RedirectResponse(f"/mandates?selected={mandate.id}", status_code=303)


def _duration(run: DailyRun) -> str | None:
    if run.finished_at is None:
        return None
    seconds = int((run.finished_at - run.started_at).total_seconds())
    return f"{seconds // 60} min {seconds % 60:02d} s" if seconds >= 60 else f"{seconds} s"


def _run_issues(run: DailyRun) -> tuple[int, int]:
    """(erreurs, avertissements) comptés dans les détails ; repli sur les anciens runs."""
    stats = run.stats or {}
    details = stats.get("details")
    if details is None:
        return len(stats.get("errors") or []) + (1 if run.error else 0), int(
            stats.get("source_warnings") or 0
        )
    levels = [i["level"] for d in details for i in d.get("issues", [])]
    return levels.count("error") + (1 if run.error else 0), levels.count("warning")


@router.get("/runs", response_class=HTMLResponse)
async def runs_page(request: Request, session: SessionDep, launched: int = 0):
    runs = top_level_runs(
        list(
            (
                await session.execute(
                    select(DailyRun).order_by(DailyRun.started_at.desc()).limit(150)
                )
            )
            .scalars()
            .all()
        )
    )[:50]
    rows = []
    for run in runs:
        errors, warnings = _run_issues(run)
        rows.append(
            {
                "run": run,
                "stats": run.stats or {},
                "duration": _duration(run),
                "errors": errors,
                "warnings": warnings,
            }
        )
    return _render(
        request,
        "runs.html",
        "runs",
        rows=rows,
        is_running=await running_collection(session) is not None,
        launched=bool(launched),
        source_labels=ENABLED_SOURCES,
    )


def _settings_context(*, values: dict | None = None, error: str | None = None) -> dict:
    return {
        "enabled_sources": ENABLED_SOURCES,
        "disabled_sources": DISABLED_SOURCES,
        "cantons": ROMANDY_CANTONS,
        "limits": {
            "pages": MAX_PAGES_UI,
            "listings": MAX_LISTINGS_UI,
            "details": MAX_DETAILS_UI,
        },
        "values": values
        or {
            "sources": ["anibis"],
            "cantons": list(ROMANDY_CANTONS),  # toute la Romandie par défaut
            "max_pages": "1",
            "max_listings": "10",
            "enrich_details": True,
            "max_details": "30",
        },
        "error": error,
        "import_sources": IMPORT_SOURCES,
        "import_result": None,
        "import_error": None,
    }


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, session: SessionDep):
    return _render(
        request,
        "settings.html",
        "settings",
        running=await running_collection(session) is not None,
        **_settings_context(),
    )


@router.post("/settings")
async def settings_launch(request: Request, session: SessionDep):
    form = await request.form()
    values = {
        "sources": form.getlist("sources"),
        "cantons": form.getlist("cantons"),
        "max_pages": str(form.get("max_pages") or ""),
        "max_listings": str(form.get("max_listings") or ""),
        "enrich_details": form.get("enrich_details") is not None,
        "max_details": str(form.get("max_details") or ""),
    }
    error: str | None = None
    try:
        collection = validate_request(**values)
        await launch_collection(collection)
        return RedirectResponse("/runs?launched=1", status_code=303)
    except ValueError as exc:
        error = str(exc)
    except CollectionBusyError as exc:
        error = f"{exc} Attendez qu'elle se termine (page Collectes)."
    except OSError as exc:
        error = f"Impossible de démarrer la collecte : {exc}"
    return _render(
        request,
        "settings.html",
        "settings",
        status_code=422,
        running=await running_collection(session) is not None,
        **_settings_context(values=values, error=error),
    )


@router.post("/settings/import")
async def settings_import(
    request: Request,
    session: SessionDep,
    html_file: Annotated[UploadFile, File()],
    source: Annotated[str, Form()] = "homegate",
    canton: Annotated[str, Form()] = "all",
):
    context = _settings_context()
    status_code = 200
    try:
        content = await html_file.read()
        context["import_result"] = await import_html_page(
            source=source, canton=canton, content=content
        )
    except HtmlImportError as exc:
        context["import_error"] = str(exc)
        status_code = 422
    return _render(
        request,
        "settings.html",
        "settings",
        status_code=status_code,
        running=await running_collection(session) is not None,
        **context,
    )


@router.get("/{slug}", response_class=HTMLResponse)
async def coming_soon(slug: str, request: Request):
    title = SOON_PAGES.get(slug)
    if title is None:
        raise HTTPException(status_code=404, detail="Page introuvable")
    return _render(request, "soon.html", slug, title=title)
