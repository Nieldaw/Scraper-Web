from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import make_url
from sqlalchemy.exc import InterfaceError, OperationalError

from immo_ne_collector.api.routes import router
from immo_ne_collector.config import get_settings
from immo_ne_collector.web.routes import router as web_router

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
app.include_router(router)


def _database_hint() -> str:
    url = make_url(settings.database_url)
    where = f"{url.host}:{url.port}/{url.database}"
    hint = ""
    if url.host == "db":
        hint = (
            " L'hôte « db » n'existe que dans Docker : en lançant l'application sur votre PC "
            "(make run), utilisez « localhost » dans DATABASE_URL (voir .env.example) et "
            "démarrez la base avec « make db-up »."
        )
    return f"Connexion à la base impossible ({where}).{hint}"


@app.exception_handler(OSError)
@app.exception_handler(OperationalError)
@app.exception_handler(InterfaceError)
async def database_unavailable(request: Request, exc: Exception):
    message = _database_hint()
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": message}, status_code=503)
    return HTMLResponse(
        f"<!doctype html><meta charset='utf-8'><title>Base indisponible</title>"
        f"<body style='font-family:sans-serif;max-width:40rem;margin:3rem auto'>"
        f"<h1>Base de données indisponible</h1><p>{message}</p></body>",
        status_code=503,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


# Doit rester en dernier : contient la route fourre-tout /{slug} (pages « Bientôt disponible »).
app.include_router(web_router)
