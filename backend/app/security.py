"""API-key authentication. Raw keys are returned only at creation time."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import APIKey, Tenant, utcnow

bearer = HTTPBearer(auto_error=False)
ALLOWED_SCOPES = {"jobs:read", "jobs:write", "workflows:read", "workflows:write", "workers:read", "tenants:manage", "keys:manage", "audit:read", "admin"}


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    scopes: frozenset[str]
    actor: str
    key_id: str | None = None

    def permits(self, scope: str) -> bool:
        return "admin" in self.scopes or scope in self.scopes


def hash_secret(secret: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, 250_000)
    return salt.hex() + ":" + digest.hex()


def verify_secret(secret: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(salt_hex), 250_000)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def generate_api_key() -> tuple[str, str, str]:
    raw = "qfn_live_" + secrets.token_urlsafe(36)
    key_id = "key_" + secrets.token_hex(8)
    prefix = raw[:20]
    return raw, key_id, prefix


def create_key_record(db: Session, tenant_id: str, name: str, scopes: list[str], raw: str | None = None, key_id: str | None = None, prefix: str | None = None) -> tuple[APIKey, str]:
    unknown = sorted(set(scopes) - ALLOWED_SCOPES)
    if unknown:
        raise ValueError("Unsupported scopes: " + ", ".join(unknown))
    if raw is None:
        raw, generated_id, generated_prefix = generate_api_key()
        key_id = key_id or generated_id
        prefix = prefix or generated_prefix
    if not key_id or not prefix:
        raise ValueError("API key ID and prefix must be available")
    rec = APIKey(id=key_id, name=name, prefix=prefix, secret_hash=hash_secret(raw), tenant_id=tenant_id, scopes=sorted(set(scopes)), revoked=False)
    db.add(rec)
    return rec, raw


def get_principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> Principal:
    if not settings.auth_enabled:
        tenant = db.get(Tenant, settings.default_tenant_id)
        if tenant is None:
            # startup initializes this, but keep this dependency safe in isolated tests
            tenant = Tenant(id=settings.default_tenant_id, name=settings.default_tenant_name)
            db.add(tenant)
            db.commit()
        if tenant.paused:
            raise HTTPException(status_code=423, detail="Tenant is paused")
        return Principal(tenant_id=tenant.id, scopes=frozenset(ALLOWED_SCOPES), actor="local-development")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer API key required", headers={"WWW-Authenticate": "Bearer"})
    raw = credentials.credentials
    key = db.scalar(select(APIKey).where(APIKey.prefix == raw[:20], APIKey.revoked.is_(False)))
    if key is None or not verify_secret(raw, key.secret_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key", headers={"WWW-Authenticate": "Bearer"})
    tenant = db.get(Tenant, key.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Key tenant no longer exists")
    if tenant.paused:
        raise HTTPException(status_code=423, detail="Tenant is paused")
    key.last_used_at = utcnow()
    db.commit()
    return Principal(tenant_id=key.tenant_id, scopes=frozenset(key.scopes), actor=key.name, key_id=key.id)


def require_scope(scope: str):
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.permits(scope):
            raise HTTPException(status_code=403, detail=f"Missing required scope: {scope}")
        return principal
    return dependency
