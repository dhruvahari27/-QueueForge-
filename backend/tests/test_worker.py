from __future__ import annotations

from datetime import timedelta
from app.database import SessionLocal
from app.engine import run_once
from app.models import Job, JobAttempt, utcnow


def test_worker_executes_echo_task_and_records_attempt(client):
    created = client.post("/api/jobs", json={"task_type": "echo", "payload": {"hello": "world"}}).json()
    assert run_once("test-worker") is True
    detail = client.get(f"/api/jobs/{created['id']}").json()
    assert detail["status"] == "succeeded"
    assert detail["result"] == {"echo": {"hello": "world"}}
    assert detail["attempts_count"] == 1
    assert detail["attempts"][0]["status"] == "succeeded"


def test_flaky_task_retries_then_succeeds(client):
    created = client.post("/api/jobs", json={"task_type": "flaky", "payload": {"fail_times": 1}, "max_attempts": 3}).json()
    assert run_once("test-worker") is True
    with SessionLocal() as db:
        job = db.get(Job, created["id"])
        assert job.status == "queued"
        assert job.attempts_count == 1
        job.available_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert run_once("test-worker") is True
    detail = client.get(f"/api/jobs/{created['id']}").json()
    assert detail["status"] == "succeeded"
    assert detail["attempts_count"] == 2
    assert [a["status"] for a in detail["attempts"]] == ["failed", "succeeded"]


def test_unknown_task_goes_to_dead_letter(client):
    created = client.post("/api/jobs", json={"task_type": "not.registered", "payload": {}, "max_attempts": 2}).json()
    assert run_once("test-worker") is True
    detail = client.get(f"/api/jobs/{created['id']}").json()
    assert detail["status"] == "dead"
    assert "Unknown task_type" in detail["error"]


def test_stale_worker_cannot_overwrite_a_reclaimed_attempt(client):
    from app.engine import claim_next_job, finish_job, recover_expired_leases

    created = client.post("/api/jobs", json={"task_type": "echo", "payload": {"source": "fresh"}}).json()
    with SessionLocal() as db:
        first = claim_next_job(db, "worker-old", lease_seconds=10)
        assert first is not None and first.id == created["id"]
        job = db.get(Job, created["id"])
        job.lease_expires_at = utcnow() - timedelta(seconds=1)
        job.available_at = utcnow() - timedelta(seconds=1)
        db.commit()
        assert recover_expired_leases(db) == 1
        job = db.get(Job, created["id"])
        job.available_at = utcnow() - timedelta(seconds=1)
        db.commit()
        second = claim_next_job(db, "worker-new", lease_seconds=30)
        assert second is not None and second.attempts_count == 2
        assert finish_job(db, created["id"], "worker-old", 1, {"stale": True}) is False
        assert finish_job(db, created["id"], "worker-new", 2, {"ok": True}) is True
    detail = client.get(f"/api/jobs/{created['id']}").json()
    assert detail["status"] == "succeeded"
    assert detail["result"] == {"ok": True}
    assert [attempt["status"] for attempt in detail["attempts"]] == ["lost", "succeeded"]


def test_worker_service_registers_and_shuts_down_cleanly(client, monkeypatch):
    import threading
    import app.worker as worker_service
    from app.models import Worker

    stop = threading.Event()
    monkeypatch.setattr(worker_service, "stop_event", stop)

    def run_once_then_stop(worker_id):
        assert worker_id == "lifecycle-test-worker"
        stop.set()
        return False

    monkeypatch.setattr(worker_service, "run_once", run_once_then_stop)
    monkeypatch.setattr(worker_service, "recover_expired_leases", lambda db: 0)
    worker_service.serve("lifecycle-test-worker", 0.1)

    with SessionLocal() as db:
        record = db.get(Worker, "lifecycle-test-worker")
        assert record is not None
        assert record.status == "offline"
        assert record.current_job_id is None
