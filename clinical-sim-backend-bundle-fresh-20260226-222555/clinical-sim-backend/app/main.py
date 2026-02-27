from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.health import router as health_router
from app.api.routes.reports import router as reports_router
from app.api.routes.sessions import router as sessions_router
from app.api.routes.state import router as state_router
from app.api.routes.turns import router as turns_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title=settings.app_name, version="0.1.0")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse | RedirectResponse:
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return RedirectResponse(url="/docs", status_code=307)


app.include_router(health_router)
app.include_router(sessions_router)
app.include_router(state_router)
app.include_router(turns_router)
app.include_router(reports_router)
