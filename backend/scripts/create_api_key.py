"""Create a scoped API key without printing its hash. Run from backend/: python scripts/create_api_key.py"""
from __future__ import annotations

import argparse
import secrets

from sqlalchemy import select
from app.database import Base, SessionLocal, engine
from app.models import Tenant
from app.security import ALLOWED_SCOPES, create_key_record
from app.config import settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default=settings.default_tenant_id)
    parser.add_argument("--name", required=True)
    parser.add_argument("--scope", action="append", dest="scopes", choices=sorted(ALLOWED_SCOPES - {"admin"}))
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        tenant = db.get(Tenant, args.tenant)
        if tenant is None:
            raise SystemExit(f"Tenant '{args.tenant}' not found; start the API once or create the tenant first.")
        scopes = args.scopes or ["jobs:read", "jobs:write", "workflows:read", "workflows:write", "audit:read"]
        key, raw = create_key_record(db, tenant.id, args.name, scopes)
        db.commit()
        print("API key created. Copy it now; it cannot be retrieved later.")
        print(f"Key ID: {key.id}")
        print(f"Tenant: {tenant.id}")
        print(f"Scopes: {', '.join(key.scopes)}")
        print(f"Token: {raw}")
        print("Store this token in a secret manager or environment variable. Do not commit it.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
