from __future__ import annotations

from app.models import Job
from app.database import SessionLocal


def test_health_ready(client):
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["database"] == "ok"


def test_create_list_detail_and_cancel_job(client):
    create = client.post("/api/jobs", headers={"Idempotency-Key": "order-112"}, json={
        "task_type": "echo", "queue": "critical", "priority": 8, "payload": {"message": "hello"}, "max_attempts": 3
    })
    assert create.status_code == 201, create.text
    job = create.json()
    assert job["status"] == "queued"
    assert job["payload"] == {"message": "hello"}
    again = client.post("/api/jobs", headers={"Idempotency-Key": "order-112"}, json={
        "task_type": "echo", "queue": "critical", "priority": 8,
        "payload": {"message": "hello"}, "max_attempts": 3
    })
    assert again.status_code == 200
    assert again.json()["id"] == job["id"]
    assert again.json()["idempotent_replay"] is True
    listing = client.get("/api/jobs?status=queued&search=hello")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    detail = client.get(f"/api/jobs/{job['id']}")
    assert detail.status_code == 200
    assert detail.json()["attempts"] == []
    cancel = client.post(f"/api/jobs/{job['id']}/cancel", json={"reason": "test"})
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"


def test_only_queued_jobs_can_be_cancelled(client):
    job = client.post("/api/jobs", json={"task_type": "echo", "payload": {}}).json()
    with SessionLocal() as db:
        record = db.get(Job, job["id"])
        record.status = "succeeded"
        db.commit()
    response = client.post(f"/api/jobs/{job['id']}/cancel")
    assert response.status_code == 409


def test_validation_rejects_bad_job_payload(client):
    response = client.post("/api/jobs", json={"task_type": "bad type", "payload": []})
    assert response.status_code == 422


def test_idempotency_key_cannot_be_reused_for_a_different_request(client):
    headers = {"Idempotency-Key": "invoice-58317"}
    first = client.post("/api/jobs", headers=headers, json={
        "task_type": "echo", "queue": "critical", "payload": {"invoice": 58317}
    })
    assert first.status_code == 201
    mismatch = client.post("/api/jobs", headers=headers, json={
        "task_type": "echo", "queue": "critical", "payload": {"invoice": 99999}
    })
    assert mismatch.status_code == 409
    assert "different request" in mismatch.json()["detail"]


def test_request_id_is_returned_and_metrics_are_exposed_with_low_cardinality(client):
    response = client.get("/api/health/live", headers={"X-Request-ID": "placement-demo-42"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "placement-demo-42"
    bad = client.get("/api/health/live", headers={"X-Request-ID": "not safe\r\nInjected: yes"})
    assert bad.status_code == 200
    assert "\r" not in bad.headers["X-Request-ID"]
    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert "queueforge_http_requests_total" in metrics.text
    assert "queueforge_http_request_duration_seconds" in metrics.text
