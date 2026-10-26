"""SQLAlchemy session setup; PostgreSQL is recommended for deployment."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def normalize_database_url(url: str | None) -> str:
    """Normalize database connection URLs for Railway, Heroku, and modern psycopg 3."""
    if not url:
        return "sqlite:///./queueforge.db"
    clean = url.strip()
    if clean.startswith("postgres://"):
        return "postgresql+psycopg://" + clean[len("postgres://"):]
    if clean.startswith("postgresql://") and not clean.startswith("postgresql+"):
        return "postgresql+psycopg://" + clean[len("postgresql://"):]
    return clean


def build_engine(url: str | None = None):
    target = normalize_database_url(url or settings.database_url)
    kwargs = {"pool_pre_ping": True}
    if target.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    return create_engine(target, **kwargs)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
