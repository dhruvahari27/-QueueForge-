"""QueueForge Nexus REST control plane."""
from __future__ import annotations

import json
import logging
import secrets
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import String, cast, desc, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import settings, validate_runtime_config
from .observability import (HTTP_REQUESTS, HTTP_REQUEST_DURATION, HTTP_IN_PROGRESS, JOBS_TOTAL, metrics_payload, METRICS_CONTENT_TYPE)
from .database import Base, SessionLocal, engine, get_db
from .models import APIKey, AuditEvent, Job, Tenant, Workflow, WorkflowRun, Worker, utcnow
from .schemas import APIKeyCreate, JobCancel, JobCreate, JobRetry, WorkflowCreate
from .security import ALLOWED_SCOPES, Principal, create_key_record, get_principal, require_scope
from .workflows import DAGError, reopen_workflow_job, settle_workflow_job, start_workflow_run, validate_graph

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("queueforge")


def record_audit(db: Session, tenant_id: str, actor: str, action: str, detail: str, kind: str = "info") -> None:
    db.add(AuditEvent(id="ae_" + secrets.token_hex(8), tenant_id=tenant_id, actor=actor, action=action, detail=detail[:4000], kind=kind))


def initialize_database() -> None:
    validate_runtime_config()
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        tenant = db.get(Tenant, settings.default_tenant_id)
        if tenant is None:
            db.add(Tenant(id=settings.default_tenant_id, name=settings.default_tenant_name, plan="Development", quota=100_000))
            db.commit()
        if settings.auth_enabled:
            if len(settings.bootstrap_api_key) < 32:
                raise RuntimeError("AUTH_ENABLED=true requires BOOTSTRAP_API_KEY with at least 32 characters")
            key = db.get(APIKey, "key_env_bootstrap")
            from .security import hash_secret
            if key is None:
                key = APIKey(id="key_env_bootstrap", name="Environment bootstrap key", prefix=settings.bootstrap_api_key[:20], secret_hash=hash_secret(settings.bootstrap_api_key), tenant_id=settings.default_tenant_id, scopes=sorted(ALLOWED_SCOPES), revoked=False)
                db.add(key)
            else:
                key.prefix = settings.bootstrap_api_key[:20]
                key.secret_hash = hash_secret(settings.bootstrap_api_key)
                key.revoked = False
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="QueueForge Nexus API",
    summary="Durable jobs, lease-based workers, and dependency-aware workflows.",
    description=("QueueForge Nexus is a portfolio MVP. PostgreSQL is recommended for multi-worker use. "
                 "Development mode disables API-key authentication by default; set AUTH_ENABLED=true and "
                 "BOOTSTRAP_API_KEY before exposing the API to a network."),
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Keep a caller-provided correlation ID only if it is bounded and header-safe.
    supplied = request.headers.get("X-Request-ID", "")
    request_id = supplied if len(supplied) <= 64 and re.fullmatch(r"[A-Za-z0-9._:-]+", supplied or "") else uuid.uuid4().hex
    request.state.request_id = request_id
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_payload_bytes + 16_384:
        response = JSONResponse(status_code=413, content={"detail": "Request body exceeds configured limit", "request_id": request_id})
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response
    start = time.perf_counter()
    route = "unmatched"
    HTTP_IN_PROGRESS.labels(request.method).inc()
    try:
        response = await call_next(request)
        route_obj = request.scope.get("route")
        if route_obj is not None:
            route = getattr(route_obj, "path", route)
        HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store" if request.url.path.startswith("/api") else "no-cache")
        return response
    finally:
        elapsed = time.perf_counter() - start
        HTTP_REQUEST_DURATION.labels(request.method, route).observe(elapsed)
        HTTP_IN_PROGRESS.labels(request.method).dec()
        logger.info("HTTP %s %s request_id=%s duration_ms=%.2f", request.method, route, request_id, elapsed * 1000)


@app.exception_handler(DAGError)
async def dag_error_handler(request: Request, exc: DAGError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def _job_dict(job: Job, include_attempts: bool = False) -> dict[str, Any]:
    d = {
        "id": job.id, "tenant_id": job.tenant_id, "task_type": job.task_type, "queue": job.queue,
        "status": job.status, "priority": job.priority, "payload": job.payload, "result": job.result,
        "error": job.error, "attempts_count": job.attempts_count, "max_attempts": job.max_attempts,
        "worker_id": job.worker_id, "lease_expires_at": job.lease_expires_at,
        "created_at": job.created_at, "available_at": job.available_at, "started_at": job.started_at,
        "finished_at": job.finished_at, "workflow_run_id": job.workflow_run_id,
        "workflow_node_id": job.workflow_node_id,
    }
    if include_attempts:
        d["attempts"] = [{"id": a.id, "attempt_number": a.attempt_number, "worker_id": a.worker_id,
                          "status": a.status, "error": a.error, "result": a.result,
                          "started_at": a.started_at, "finished_at": a.finished_at} for a in job.attempts]
    return d


def _workflow_dict(w: Workflow) -> dict[str, Any]:
    return {"id": w.id, "tenant_id": w.tenant_id, "name": w.name, "description": w.description,
            "version": w.version, "nodes": w.graph["nodes"], "edges": w.graph["edges"], "graph": w.graph,
            "created_at": w.created_at}


def _run_dict(run: WorkflowRun) -> dict[str, Any]:
    return {"id": run.id, "tenant_id": run.tenant_id, "workflow_id": run.workflow_id,
            "workflow_name": run.workflow_name, "workflow_version": run.workflow_version,
            "status": run.status, "nodes": run.graph["nodes"], "edges": run.graph["edges"],
            "node_states": run.node_states, "created_at": run.created_at, "finished_at": run.finished_at}


def _tenant_filter(query, model, tenant_id: str):
    return query.where(model.tenant_id == tenant_id)


def _require_tenant_active(db: Session, principal: Principal) -> Tenant:
    # Lock the tenant row during submission so monthly quota checks serialize on PostgreSQL.
    tenant = db.scalar(select(Tenant).where(Tenant.id == principal.tenant_id).with_for_update())
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant not found")
    if tenant.paused:
        raise HTTPException(status_code=423, detail="Tenant is paused")
    return tenant


def _assert_quota(db: Session, tenant: Tenant, needed: int = 1) -> None:
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count()).select_from(Job).where(Job.tenant_id == tenant.id, Job.created_at >= month_start)) or 0
    if used + needed > tenant.quota:
        raise HTTPException(status_code=429, detail="Tenant monthly job quota exceeded")


def _matches_job_request(existing: Job, body: JobCreate) -> bool:
    """An idempotency key may replay only the same logical request."""
    return (existing.task_type == body.task_type and existing.queue == body.queue
            and existing.priority == body.priority and existing.payload == body.payload
            and existing.max_attempts == body.max_attempts)


def _json_payload_size(payload: dict[str, Any]) -> int:
    try:
        return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Payload must be JSON serializable") from exc


@app.get("/api/health/live", tags=["system"])
def liveness():
    """Liveness probe: confirms the process is responsive without depending on the database."""
    return {"status": "ok", "version": app.version}


@app.get("/api/metrics", tags=["system"], response_class=Response)
def metrics(db: Session = Depends(get_db), principal: Principal = Depends(require_scope("admin"))):
    """Prometheus exposes service-wide aggregates and therefore requires platform-admin scope."""
    del principal  # authorization is the security boundary; labels intentionally contain no tenant IDs.
    counts = {row[0]: row[1] for row in db.execute(select(Job.status, func.count()).group_by(Job.status)).all()}
    for state_name in ("queued", "running", "succeeded", "dead", "cancelled"):
        JOBS_TOTAL.labels(state_name).set(int(counts.get(state_name, 0)))
    return Response(content=metrics_payload(), media_type=METRICS_CONTENT_TYPE)


@app.get("/api/health", tags=["system"])
@app.get("/api/health/ready", tags=["system"], include_in_schema=False)
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok", "auth_enabled": settings.auth_enabled, "version": app.version, "time": utcnow()}
    except Exception as exc:
        logger.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Database is not ready") from exc


@app.get("/api/dashboard", tags=["system"])
def dashboard(db: Session = Depends(get_db), principal: Principal = Depends(require_scope("jobs:read"))):
    tid = principal.tenant_id
    counts = {s: db.scalar(select(func.count()).select_from(Job).where(Job.tenant_id == tid, Job.status == s)) or 0
              for s in ("queued", "running", "succeeded", "dead", "cancelled")}
    # Worker identities are service-wide rather than tenant-owned. Only reveal them
    # to principals with an explicit workers:read grant.
    workers = db.scalars(select(Worker).order_by(desc(Worker.last_heartbeat)).limit(100)).all() if principal.permits("workers:read") else []
    recent = db.scalars(select(Job).where(Job.tenant_id == tid).order_by(desc(Job.created_at)).limit(8)).all()
    active_workers = sum(1 for w in workers if w.status in ("idle", "busy") and _fresh(w.last_heartbeat)) if principal.permits("workers:read") else None
    return {"job_counts": counts, "total_jobs": sum(counts.values()), "workers": [{"id": w.id, "hostname": w.hostname, "status": w.status, "current_job_id": w.current_job_id, "last_heartbeat": w.last_heartbeat, "concurrency": w.concurrency} for w in workers], "active_workers": active_workers, "recent_jobs": [_job_dict(j) for j in recent], "data_mode": "live-database"}


def _fresh(value: datetime | None) -> bool:
    if value is None:
        return False
    now = utcnow()
    if value.tzinfo is None:
        now = now.replace(tzinfo=None)
    return value >= now - timedelta(seconds=settings.lease_seconds * 2)


@app.get("/api/jobs", tags=["jobs"])
def list_jobs(status_filter: str | None = Query(default=None, alias="status", pattern="^(queued|running|succeeded|dead|failed|cancelled)$"),
              queue: str | None = Query(default=None, max_length=80), search: str | None = Query(default=None, max_length=200),
              limit: int = Query(default=50, ge=1, le=250), offset: int = Query(default=0, ge=0),
              db: Session = Depends(get_db), principal: Principal = Depends(require_scope("jobs:read"))):
    query = select(Job).where(Job.tenant_id == principal.tenant_id)
    if status_filter:
        query = query.where(Job.status == ("dead" if status_filter == "failed" else status_filter))
    if queue:
        query = query.where(Job.queue == queue)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where((Job.id.ilike(pattern)) | (Job.task_type.ilike(pattern)) | (Job.queue.ilike(pattern)) | (cast(Job.payload, String).ilike(pattern)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(desc(Job.created_at)).offset(offset).limit(limit)).all()
    return {"items": [_job_dict(j) for j in rows], "total": total, "limit": limit, "offset": offset}


@app.post("/api/jobs", status_code=201, tags=["jobs"])
def create_job(body: JobCreate, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=220),
               db: Session = Depends(get_db), principal: Principal = Depends(require_scope("jobs:write"))):
    tenant = _require_tenant_active(db, principal)
    if _json_payload_size(body.payload) > settings.max_payload_bytes:
        raise HTTPException(status_code=413, detail=f"Payload exceeds {settings.max_payload_bytes} bytes")
    if idempotency_key:
        existing = db.scalar(select(Job).where(Job.tenant_id == tenant.id, Job.idempotency_key == idempotency_key))
        if existing:
            if not _matches_job_request(existing, body):
                raise HTTPException(status_code=409, detail="Idempotency-Key was already used with a different request")
            return JSONResponse(status_code=200, content=jsonable_encoder({**_job_dict(existing), "idempotent_replay": True}))
    _assert_quota(db, tenant, 1)
    job = Job(id="jf_" + secrets.token_hex(7), tenant_id=tenant.id, task_type=body.task_type, queue=body.queue,
              status="queued", priority=body.priority, payload=body.payload, max_attempts=body.max_attempts,
              idempotency_key=idempotency_key, available_at=utcnow())
    db.add(job)
    record_audit(db, tenant.id, principal.actor, "job.created", f"{job.id} · {job.task_type}", "ok")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = db.scalar(select(Job).where(Job.tenant_id == tenant.id, Job.idempotency_key == idempotency_key))
            if existing and _matches_job_request(existing, body):
                return JSONResponse(status_code=200, content=jsonable_encoder({**_job_dict(existing), "idempotent_replay": True}))
            if existing:
                raise HTTPException(status_code=409, detail="Idempotency-Key was already used with a different request")
        raise HTTPException(status_code=409, detail="Job conflicts with an existing record")
    db.refresh(job)
    return _job_dict(job)


@app.get("/api/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("jobs:read"))):
    job = db.scalar(select(Job).options(selectinload(Job.attempts)).where(Job.id == job_id, Job.tenant_id == principal.tenant_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_dict(job, include_attempts=True)


@app.post("/api/jobs/{job_id}/retry", tags=["jobs"])
def retry_job(job_id: str, body: JobRetry | None = None, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("jobs:write"))):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == principal.tenant_id).with_for_update())
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"dead", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Cannot retry a job in '{job.status}' state")
    # Attempt numbers must stay unique per job (uq_job_attempt_number) and the attempt history is an
    # audit trail, so a manual retry keeps attempts_count and grants a fresh budget on top of it
    # instead of resetting the counter (which made the next worker claim violate the constraint and
    # wedge the head of the queue).
    budget = max(1, job.max_attempts)
    job.max_attempts = min(job.attempts_count + budget, 1000)
    job.status = "queued"
    job.error = None
    job.result = None
    job.worker_id = None
    job.lease_expires_at = None
    job.started_at = None
    job.finished_at = None
    job.available_at = utcnow()
    reopen_workflow_job(db, job)
    record_audit(db, job.tenant_id, principal.actor, "job.retried", f"{job.id} · {(body.reason if body else 'operator_retry')}", "ok")
    db.commit()
    db.refresh(job)
    return _job_dict(job)


@app.post("/api/jobs/{job_id}/cancel", tags=["jobs"])
def cancel_job(job_id: str, body: JobCancel | None = None, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("jobs:write"))):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == principal.tenant_id).with_for_update())
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "queued":
        raise HTTPException(status_code=409, detail="Only queued jobs can be cancelled safely")
    job.status = "cancelled"
    job.finished_at = utcnow()
    settle_workflow_job(db, job)
    record_audit(db, job.tenant_id, principal.actor, "job.cancelled", f"{job.id} · {(body.reason if body else 'operator_cancel')}", "warn")
    db.commit()
    db.refresh(job)
    return _job_dict(job)


@app.get("/api/workers", tags=["workers"])
def list_workers(db: Session = Depends(get_db), principal: Principal = Depends(require_scope("workers:read"))):
    rows = db.scalars(select(Worker).order_by(desc(Worker.last_heartbeat)).limit(250)).all()
    return {"items": [{"id": w.id, "hostname": w.hostname, "status": w.status if _fresh(w.last_heartbeat) else "stale",
                       "current_job_id": w.current_job_id, "last_heartbeat": w.last_heartbeat, "concurrency": w.concurrency,
                       "metadata": w.metadata_json} for w in rows], "total": len(rows)}


@app.get("/api/workflows", tags=["workflows"])
def list_workflows(db: Session = Depends(get_db), principal: Principal = Depends(require_scope("workflows:read"))):
    rows = db.scalars(select(Workflow).where(Workflow.tenant_id == principal.tenant_id).order_by(desc(Workflow.created_at)).limit(250)).all()
    return {"items": [_workflow_dict(w) for w in rows], "total": len(rows)}


@app.post("/api/workflows", status_code=201, tags=["workflows"])
def create_workflow(body: WorkflowCreate, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("workflows:write"))):
    graph = {"nodes": [n.model_dump() for n in body.nodes], "edges": [e.model_dump() for e in body.edges]}
    validate_graph(graph)
    dup = db.scalar(select(Workflow).where(Workflow.tenant_id == principal.tenant_id, Workflow.name == body.name).order_by(desc(Workflow.version)))
    version = dup.version + 1 if dup else 1
    workflow = Workflow(id="wf_" + secrets.token_hex(7), tenant_id=principal.tenant_id, name=body.name, description=body.description, version=version, graph=graph)
    db.add(workflow)
    record_audit(db, principal.tenant_id, principal.actor, "workflow.created", f"{workflow.name} v{version}", "ok")
    db.commit()
    db.refresh(workflow)
    return _workflow_dict(workflow)


@app.post("/api/workflows/validate", tags=["workflows"])
def validate_workflow(body: WorkflowCreate, principal: Principal = Depends(require_scope("workflows:write"))):
    graph = {"nodes": [n.model_dump() for n in body.nodes], "edges": [e.model_dump() for e in body.edges]}
    return validate_graph(graph)


@app.post("/api/workflows/{workflow_id}/runs", status_code=201, tags=["workflows"])
def run_workflow(workflow_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("workflows:write"))):
    workflow = db.scalar(select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == principal.tenant_id))
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    tenant = _require_tenant_active(db, principal)
    _assert_quota(db, tenant, len(workflow.graph["nodes"]))
    run = start_workflow_run(db, workflow, principal.tenant_id)
    record_audit(db, principal.tenant_id, principal.actor, "workflow.run_started", f"{workflow.name} · {run.id}", "ok")
    db.commit()
    db.refresh(run)
    return _run_dict(run)


@app.get("/api/workflows/runs/{run_id}", tags=["workflows"])
def get_workflow_run(run_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("workflows:read"))):
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.tenant_id == principal.tenant_id))
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return _run_dict(run)


@app.get("/api/audit", tags=["audit"])
def list_audit(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db), principal: Principal = Depends(require_scope("audit:read"))):
    rows = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == principal.tenant_id).order_by(desc(AuditEvent.created_at)).limit(limit)).all()
    return {"items": [{"id": e.id, "tenant_id": e.tenant_id, "actor": e.actor, "kind": e.kind, "action": e.action, "detail": e.detail, "created_at": e.created_at} for e in rows], "total": len(rows)}


@app.get("/api/tenants/current", tags=["tenants"])
def current_tenant(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    tenant = _require_tenant_active(db, principal)
    return {"id": tenant.id, "name": tenant.name, "plan": tenant.plan, "quota": tenant.quota, "paused": tenant.paused, "created_at": tenant.created_at}


@app.get("/api/keys", tags=["security"])
def list_keys(db: Session = Depends(get_db), principal: Principal = Depends(require_scope("keys:manage"))):
    rows = db.scalars(select(APIKey).where(APIKey.tenant_id == principal.tenant_id).order_by(desc(APIKey.created_at))).all()
    return {"items": [{"id": k.id, "name": k.name, "prefix": k.prefix, "scopes": k.scopes, "revoked": k.revoked, "created_at": k.created_at, "last_used_at": k.last_used_at} for k in rows]}


@app.post("/api/keys", status_code=201, tags=["security"])
def create_api_key(body: APIKeyCreate, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("keys:manage"))):
    if not body.scopes or len(body.scopes) > 20:
        raise HTTPException(status_code=422, detail="Provide between 1 and 20 scopes")
    if "admin" in body.scopes and not principal.permits("admin"):
        raise HTTPException(status_code=403, detail="Only an administrator may create an admin key")
    if "workers:read" in body.scopes and not principal.permits("admin"):
        raise HTTPException(status_code=403, detail="Only a platform administrator may grant system-wide worker visibility")
    try:
        key, raw = create_key_record(db, principal.tenant_id, body.name, body.scopes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit(db, principal.tenant_id, principal.actor, "api_key.created", f"{key.id} · {key.name}", "warn")
    db.commit()
    return {"id": key.id, "name": key.name, "token": raw, "prefix": key.prefix, "scopes": key.scopes, "warning": "This token is shown once. Store it securely; the server stores only a salted hash."}


@app.post("/api/keys/{key_id}/revoke", tags=["security"])
def revoke_api_key(key_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_scope("keys:manage"))):
    key = db.scalar(select(APIKey).where(APIKey.id == key_id, APIKey.tenant_id == principal.tenant_id).with_for_update())
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    key.revoked = True
    record_audit(db, principal.tenant_id, principal.actor, "api_key.revoked", key.id, "warn")
    db.commit()
    return {"id": key.id, "revoked": True}


@app.get("/api/", tags=["system"])
def api_root():
    return {"name": "QueueForge Nexus API", "version": app.version, "docs": "/docs", "health": "/api/health"}
