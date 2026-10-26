from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_queueforge_nexus.db")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("LEASE_SECONDS", "30")
os.environ.setdefault("APP_ENV", "development")

from app.main import app
from app.database import Base, engine, SessionLocal
from app.models import Tenant


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.add(Tenant(id="demo", name="Nexus Labs", quota=100000))
    db.commit()
    db.close()
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
