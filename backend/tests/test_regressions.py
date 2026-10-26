"""Regression tests for bugs found by running the stack end to end (retry wedge, workflow cancel/retry, tenant gates)."""
from __future__ import annotations

from app.database import SessionLocal
from app.engine import run_once
from app.models import Job, Tenant


def _wf(client, name="wf"):
    body = {"name": name, "nodes": [
        {"id": "a", "title": "A", "task_type": "echo", "payload": {}},
        {"id": "b", "title": "B", "task_type": "echo", "payload": {}}],
        "edges": [{"source": "a", "target": "b"}]}
    return client.post("/api/workflows", json=body).json()


def test_manual_retry_keeps_attempt_history_and_job_can_run_again(client):
    """Used to violate uq_job_attempt_number on the next claim and starve the whole queue."""
    jid = client.post("/api/jobs", json={"task_type": "not.registered", "payload": {}, "max_attempts": 1}).json()["id"]
    assert run_once("w") is True
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "dead"
    retried = client.post(f"/api/jobs/{jid}/retry", json={}).json()
    assert retried["status"] == "queued" and retried["attempts_count"] == 1 and retried["max_attempts"] == 2
    other = client.post("/api/jobs", json={"task_type": "echo", "payload": {"x": 1}}).json()["id"]
    assert run_once("w") is True  # claims the retried job without an IntegrityError
    detail = client.get(f"/api/jobs/{jid}").json()
    assert [a["attempt_number"] for a in detail["attempts"]] == [1, 2]
    assert run_once("w") is True  # the queue is not wedged: the next job runs too
    assert client.get(f"/api/jobs/{other}").json()["status"] == "succeeded"


def test_cancelling_a_workflow_job_settles_the_run(client):
    run = client.post(f"/api/workflows/{_wf(client)['id']}/runs").json()
    first = run["node_states"]["a"]["job_id"]
    assert client.post(f"/api/jobs/{first}/cancel", json={}).status_code == 200
    state = client.get(f"/api/workflows/runs/{run['id']}").json()
    assert state["status"] == "cancelled"
    assert state["node_states"]["a"]["status"] == "cancelled"
    assert state["node_states"]["b"]["status"] == "blocked"


def test_retrying_a_failed_workflow_node_resumes_the_run(client):
    body = {"name": "fail-first", "nodes": [
        {"id": "a", "title": "A", "task_type": "sum", "payload": {"numbers": "bad"}},
        {"id": "b", "title": "B", "task_type": "echo", "payload": {}}], "edges": [{"source": "a", "target": "b"}]}
    wf = client.post("/api/workflows", json=body).json()
    run = client.post(f"/api/workflows/{wf['id']}/runs").json()
    assert run_once("w") is True
    failed = client.get(f"/api/workflows/runs/{run['id']}").json()
    assert failed["status"] == "failed" and failed["node_states"]["b"]["status"] == "blocked"
    job_id = failed["node_states"]["a"]["job_id"]
    with SessionLocal() as db:  # make the task fixable, as an operator would
        db.get(Job, job_id).payload = {"numbers": [1, 2]}
        db.commit()
    assert client.post(f"/api/jobs/{job_id}/retry", json={}).status_code == 200
    assert client.get(f"/api/workflows/runs/{run['id']}").json()["status"] == "running"
    assert run_once("w") is True and run_once("w") is True
    done = client.get(f"/api/workflows/runs/{run['id']}").json()
    assert done["status"] == "succeeded"
    assert done["node_states"]["b"]["status"] == "succeeded"


def test_paused_tenant_and_quota_apply_to_workflow_runs(client):
    wf = _wf(client)
    with SessionLocal() as db:
        db.get(Tenant, "demo").quota = 1
        db.commit()
    assert client.post(f"/api/workflows/{wf['id']}/runs").status_code == 429  # needs 2 jobs, quota is 1
    with SessionLocal() as db:
        t = db.get(Tenant, "demo")
        t.quota, t.paused = 1000, True
        db.commit()
    assert client.post(f"/api/workflows/{wf['id']}/runs").status_code == 423
