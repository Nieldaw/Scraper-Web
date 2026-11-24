from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from immo_ne_collector.api.routes import router
from immo_ne_collector.config import get_settings
from immo_ne_collector.web.routes import router as web_router

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


# Doit rester en dernier : contient la route fourre-tout /{slug} (pages « Bientôt disponible »).
app.include_router(web_router)
