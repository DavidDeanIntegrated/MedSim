from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.admin_inputs import router as admin_inputs_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.cases import router as cases_router
from app.api.routes.health import router as health_router
from app.api.routes.lti import router as lti_router
from app.api.routes.reports import router as reports_router
from app.api.routes.sessions import router as sessions_router
from app.api.routes.state import router as state_router
from app.api.routes.stream import router as stream_router
from app.api.routes.turns import router as turns_router
from app.auth.routes import router as auth_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.engine import init_db

configure_logging()
settings = get_settings()

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title=settings.app_name, version="0.4.0")

# CORS — allow Vite dev server (port 5173) during local development
if settings.app_env != "production":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Initialize database tables on startup
init_db()

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False, response_model=None)
def root() -> FileResponse | RedirectResponse:
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return RedirectResponse(url="/docs", status_code=307)


@app.get("/educator", include_in_schema=False, response_model=None)
def educator_dashboard() -> FileResponse | RedirectResponse:
    page = FRONTEND_DIR / "educator.html"
    if page.exists():
        return FileResponse(page)
    return RedirectResponse(url="/docs", status_code=307)


@app.get("/admin/dashboard", include_in_schema=False, response_model=None)
def admin_dashboard() -> FileResponse | RedirectResponse:
    page = FRONTEND_DIR / "admin_inputs.html"
    if page.exists():
        return FileResponse(page)
    return RedirectResponse(url="/docs", status_code=307)


# Auth
app.include_router(auth_router)

# API
app.include_router(health_router)
app.include_router(cases_router)
app.include_router(sessions_router)
app.include_router(state_router)
app.include_router(stream_router)
app.include_router(turns_router)
app.include_router(reports_router)
app.include_router(analytics_router)
app.include_router(lti_router)
app.include_router(admin_inputs_router)
