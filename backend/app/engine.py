"""Lease-based worker engine. PostgreSQL is the multi-process reference database."""
from __future__ import annotations

import logging
import socket
import time
import threading
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import AuditEvent, Job, JobAttempt, Worker, utcnow
from .workflows import settle_workflow_job

log = logging.getLogger("queueforge.engine")


class RetryableTaskError(RuntimeError):
    pass


class PermanentTaskError(RuntimeError):
    pass


def task_echo(payload: dict[str, Any], attempt: int) -> dict[str, Any]:
    return {"echo": payload}


def task_sum(payload: dict[str, Any], attempt: int) -> dict[str, Any]:
    numbers = payload.get("numbers")
    if not isinstance(numbers, list) or not numbers or any(not isinstance(n, (int, float)) or isinstance(n, bool) for n in numbers):
        raise PermanentTaskError("sum task requires a non-empty numeric 'numbers' array")
    return {"sum": sum(numbers), "count": len(numbers)}


def task_sleep(payload: dict[str, Any], attempt: int) -> dict[str, Any]:
    seconds = payload.get("seconds", 1)
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds < 0 or seconds > settings.max_sleep_seconds:
        raise PermanentTaskError(f"seconds must be between 0 and {settings.max_sleep_seconds}")
    time.sleep(float(seconds))
    return {"slept_seconds": float(seconds)}


def task_flaky(payload: dict[str, Any], attempt: int) -> dict[str, Any]:
    fail_times = payload.get("fail_times", 1)
    if not isinstance(fail_times, int) or fail_times < 0 or fail_times > 20:
        raise PermanentTaskError("fail_times must be an integer between 0 and 20")
    if attempt <= fail_times:
        raise RetryableTaskError(f"Intentional test failure on attempt {attempt} of {fail_times}")
    return {"ok": True, "succeeded_on_attempt": attempt}


TASKS = {"echo": task_echo, "sum": task_sum, "sleep": task_sleep, "flaky": task_flaky}


def _audit(db: Session, tenant_id: str, action: str, detail: str, kind: str = "info", actor: str = "worker") -> None:
    import secrets
    db.add(AuditEvent(id="ae_" + secrets.token_hex(8), tenant_id=tenant_id, actor=actor, action=action, detail=detail[:4000], kind=kind))


def ensure_worker(db: Session, worker_id: str, concurrency: int = 1) -> Worker:
    worker = db.get(Worker, worker_id)
    if worker is None:
        worker = Worker(id=worker_id, hostname=socket.gethostname(), status="idle", concurrency=max(1, concurrency), metadata_json={"engine": "sql-lease-v1"})
        db.add(worker)
    worker.last_heartbeat = utcnow()
    worker.status = "idle" if worker.current_job_id is None else "busy"
    return worker


def recover_expired_leases(db: Session) -> int:
    now = utcnow()
    rows = db.scalars(select(Job).where(Job.status == "running", Job.lease_expires_at.is_not(None), Job.lease_expires_at < now).with_for_update(skip_locked=True)).all()
    recovered = 0
    for job in rows:
        attempt = db.scalar(select(JobAttempt).where(JobAttempt.job_id == job.id, JobAttempt.attempt_number == job.attempts_count))
        if attempt and attempt.status == "running":
            attempt.status = "lost"
            attempt.error = "Worker lease expired before completion"
            attempt.finished_at = now
        old_worker = job.worker_id
        job.worker_id = None
        job.lease_expires_at = None
        if job.attempts_count < job.max_attempts:
            delay = min(300, 2 ** max(0, job.attempts_count - 1))
            job.status = "queued"
            job.available_at = now + timedelta(seconds=delay)
            job.error = "Worker lease expired; scheduled for recovery"
            _audit(db, job.tenant_id, "job.lease_recovered", f"{job.id} from {old_worker or 'unknown worker'}", "warn")
        else:
            job.status = "dead"
            job.finished_at = now
            job.error = "Worker lease expired after max attempts"
            settle_workflow_job(db, job)
            _audit(db, job.tenant_id, "job.dead_lettered", f"{job.id} lease expired", "warn")
        worker = db.get(Worker, old_worker) if old_worker else None
        if worker:
            worker.status = "stale"
            worker.current_job_id = None
        recovered += 1
    if recovered:
        db.commit()
    return recovered


def claim_next_job(db: Session, worker_id: str, lease_seconds: int | None = None) -> Job | None:
    ensure_worker(db, worker_id)
    db.flush()
    recover_expired_leases(db)
    now = utcnow()
    stmt = (select(Job).where(Job.status == "queued", Job.available_at <= now)
            .order_by(Job.priority.desc(), Job.created_at.asc())
            .limit(1).with_for_update(skip_locked=True))
    job = db.scalar(stmt)
    if job is None:
        worker = db.get(Worker, worker_id)
        if worker:
            worker.status = "idle"
            worker.current_job_id = None
            worker.last_heartbeat = now
            db.commit()
        else:
            db.commit()
        return None
    job.status = "running"
    job.worker_id = worker_id
    job.attempts_count += 1
    job.started_at = job.started_at or now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds or settings.lease_seconds)
    job.error = None
    attempt = JobAttempt(job_id=job.id, attempt_number=job.attempts_count, worker_id=worker_id, status="running", started_at=now)
    db.add(attempt)
    worker = db.get(Worker, worker_id)
    worker.status = "busy"
    worker.current_job_id = job.id
    worker.last_heartbeat = now
    db.commit()
    db.refresh(job)
    return job


def renew_lease(job_id: str, worker_id: str, attempt_number: int) -> bool:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        now = utcnow()
        if not job or job.status != "running" or job.worker_id != worker_id or job.attempts_count != attempt_number:
            return False
        job.lease_expires_at = now + timedelta(seconds=settings.lease_seconds)
        worker = db.get(Worker, worker_id)
        if worker:
            worker.last_heartbeat = now
            worker.current_job_id = job_id
            worker.status = "busy"
        db.commit()
        return True
    finally:
        db.close()


def finish_job(db: Session, job_id: str, worker_id: str, attempt_number: int, result: dict[str, Any]) -> bool:
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job or job.status != "running" or job.worker_id != worker_id or job.attempts_count != attempt_number:
        return False  # a reclaimed/fenced-out worker cannot overwrite the current attempt
    now = utcnow()
    attempt = db.scalar(select(JobAttempt).where(JobAttempt.job_id == job.id, JobAttempt.attempt_number == attempt_number))
    if attempt:
        attempt.status = "succeeded"
        attempt.result = result
        attempt.finished_at = now
    job.status = "succeeded"
    job.result = result
    job.error = None
    job.finished_at = now
    job.lease_expires_at = None
    worker = db.get(Worker, worker_id)
    if worker:
        worker.status = "idle"
        worker.current_job_id = None
        worker.last_heartbeat = now
    settle_workflow_job(db, job)
    _audit(db, job.tenant_id, "job.succeeded", f"{job.id} completed by {worker_id}", "ok")
    db.commit()
    return True


def fail_job(db: Session, job_id: str, worker_id: str, attempt_number: int, error: Exception, permanent: bool = False) -> bool:
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job or job.status != "running" or job.worker_id != worker_id or job.attempts_count != attempt_number:
        return False
    now = utcnow()
    message = str(error)[:4000] or error.__class__.__name__
    attempt = db.scalar(select(JobAttempt).where(JobAttempt.job_id == job.id, JobAttempt.attempt_number == attempt_number))
    if attempt:
        attempt.status = "failed"
        attempt.error = message
        attempt.finished_at = now
    job.error = message
    job.worker_id = None
    job.lease_expires_at = None
    worker = db.get(Worker, worker_id)
    if worker:
        worker.status = "idle"
        worker.current_job_id = None
        worker.last_heartbeat = now
    if not permanent and job.attempts_count < job.max_attempts:
        delay = min(300, 2 ** max(0, job.attempts_count - 1))
        job.status = "queued"
        job.available_at = now + timedelta(seconds=delay)
        _audit(db, job.tenant_id, "job.retry_scheduled", f"{job.id} retry in {delay}s: {message}", "warn")
    else:
        job.status = "dead"
        job.finished_at = now
        settle_workflow_job(db, job)
        _audit(db, job.tenant_id, "job.dead_lettered", f"{job.id}: {message}", "warn")
    db.commit()
    return True


def execute_task(task_type: str, payload: dict[str, Any], attempt_number: int) -> dict[str, Any]:
    handler = TASKS.get(task_type)
    if handler is None:
        raise PermanentTaskError(f"Unknown task_type '{task_type}'. Registered tasks: {', '.join(sorted(TASKS))}")
    return handler(payload, attempt_number)


def run_once(worker_id: str) -> bool:
    db = SessionLocal()
    try:
        job = claim_next_job(db, worker_id)
        if job is None:
            return False
        job_id, attempt_number, task_type, payload = job.id, job.attempts_count, job.task_type, dict(job.payload or {})
    finally:
        db.close()
    lease_stop = threading.Event()
    lease_lost = threading.Event()

    def lease_heartbeat():
        interval = max(1.0, settings.lease_seconds / 3)
        while not lease_stop.wait(interval):
            try:
                if not renew_lease(job_id, worker_id, attempt_number):
                    lease_lost.set()
                    return
            except Exception:
                # A temporary database error is retried on the next heartbeat;
                # fencing still prevents a stale worker overwriting a newer attempt.
                log.warning("Lease heartbeat for %s failed; retrying on next interval", job_id, exc_info=True)

    lease_thread = threading.Thread(target=lease_heartbeat, daemon=True, name=f"lease-{job_id}")
    lease_thread.start()
    try:
        result = execute_task(task_type, payload, attempt_number)
    except PermanentTaskError as exc:
        err, permanent = exc, True
    except Exception as exc:  # task errors must not terminate the worker loop
        err, permanent = exc, False
    else:
        lease_stop.set()
        lease_thread.join(timeout=2)
        db = SessionLocal()
        try:
            finish_job(db, job_id, worker_id, attempt_number, result)
        finally:
            db.close()
        return True
    finally:
        lease_stop.set()
        lease_thread.join(timeout=2)
    db = SessionLocal()
    try:
        fail_job(db, job_id, worker_id, attempt_number, err, permanent)
    finally:
        db.close()
    return True
