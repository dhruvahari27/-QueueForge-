from __future__ import annotations
from types import SimpleNamespace

import app.security as security
from app.database import SessionLocal
from app.models import Job, Tenant
from app.security import create_key_record, hash_secret, verify_secret


def test_secret_hash_uses_salt_and_verifies():
    stored = hash_secret('a-very-long-test-token')
    assert stored != 'a-very-long-test-token'
    assert verify_secret('a-very-long-test-token', stored)
    assert not verify_secret('wrong-token', stored)
    assert hash_secret('a-very-long-test-token') != stored


def test_api_key_auth_enforces_scope_and_tenant(client, monkeypatch):
    with SessionLocal() as db:
        db.add(Tenant(id='other', name='Other tenant'))
        db.flush()  # PostgreSQL enforces the jobs.tenant_id foreign key; SQLite does not
        db.add(Job(id='jf_other_001', tenant_id='other', task_type='echo', queue='default', status='queued', priority=5, payload={}, attempts_count=0, max_attempts=3))
        rec, raw = create_key_record(db, 'demo', 'reader', ['jobs:read'])
        key_manager, manager_raw = create_key_record(db, 'demo', 'key manager', ['jobs:read', 'keys:manage'])
        audit_key, audit_raw = create_key_record(db, 'demo', 'audit-only reader', ['jobs:read', 'audit:read'])
        db.commit()
    monkeypatch.setattr(security, 'settings', SimpleNamespace(auth_enabled=True, default_tenant_id='demo', default_tenant_name='Nexus Labs'))
    missing = client.get('/api/jobs')
    assert missing.status_code == 401
    assert client.get('/api/jobs', headers={'Authorization': 'Bearer ' + raw}).json()['total'] == 0
    assert client.get('/api/jobs/jf_other_001', headers={'Authorization': 'Bearer ' + raw}).status_code == 404
    dashboard = client.get('/api/dashboard', headers={'Authorization': 'Bearer ' + raw}).json()
    assert dashboard['workers'] == [] and dashboard['active_workers'] is None
    assert client.get('/api/workers', headers={'Authorization': 'Bearer ' + raw}).status_code == 403
    assert client.get('/api/metrics', headers={'Authorization': 'Bearer ' + raw}).status_code == 403
    # Tenant-scoped audit permission must not reveal service-wide Prometheus totals.
    assert client.get('/api/metrics', headers={'Authorization': 'Bearer ' + audit_raw}).status_code == 403
    # A tenant key manager cannot grant a system-wide worker inventory scope.
    global_scope = client.post('/api/keys', headers={'Authorization': 'Bearer ' + manager_raw}, json={
        'name': 'unsafe worker reader', 'scopes': ['workers:read']
    })
    assert global_scope.status_code == 403
    denied = client.post('/api/jobs', headers={'Authorization': 'Bearer ' + raw}, json={'task_type':'echo','payload':{}})
    assert denied.status_code == 403


def test_key_rotation_and_revocation_are_effective(client, monkeypatch):
    with SessionLocal() as db:
        admin, admin_raw = create_key_record(db, 'demo', 'admin test key', ['admin'])
        db.commit()
    monkeypatch.setattr(security, 'settings', SimpleNamespace(auth_enabled=True, default_tenant_id='demo', default_tenant_name='Nexus Labs'))
    made = client.post('/api/keys', headers={'Authorization': 'Bearer ' + admin_raw}, json={
        'name': 'temporary monitor', 'scopes': ['jobs:read']
    })
    assert made.status_code == 201, made.text
    raw = made.json()['token']
    assert client.get('/api/jobs', headers={'Authorization': 'Bearer ' + raw}).status_code == 200
    revoked = client.post('/api/keys/' + made.json()['id'] + '/revoke', headers={'Authorization': 'Bearer ' + admin_raw})
    assert revoked.status_code == 200
    assert client.get('/api/jobs', headers={'Authorization': 'Bearer ' + raw}).status_code == 401


def test_production_configuration_fails_closed(monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "settings", SimpleNamespace(
        app_env="production", auth_enabled=False, bootstrap_api_key="",
        database_url="sqlite:///./unsafe.db", auto_create_schema=True, cors_origins=("*",),
    ))
    try:
        config.validate_runtime_config()
    except RuntimeError as exc:
        message = str(exc)
        assert "AUTH_ENABLED" in message
        assert "PostgreSQL" in message
        assert "CORS_ORIGINS" in message
    else:
        raise AssertionError("unsafe production configuration must fail")
