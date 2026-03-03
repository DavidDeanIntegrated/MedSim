"""Database engine and session management.

Uses SQLite locally, configurable to PostgreSQL (Supabase) via DATABASE_URL env var.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base

_engine = None
_SessionLocal = None


def get_db_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            echo=settings.app_env == "dev",
            connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
        )
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_db_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


def get_db() -> Session:
    """Dependency for FastAPI routes — yields a DB session."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Call at app startup."""
    engine = get_db_engine()
    Base.metadata.create_all(bind=engine)
