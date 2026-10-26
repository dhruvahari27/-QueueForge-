from __future__ import annotations

from app.database import SessionLocal
from app.models import Job, WorkflowRun
from app.engine import run_once


def graph_body():
    return {
        "name": "simple-pipeline",
        "description": "A two-step dependent pipeline",
        "nodes": [
            {"id": "start", "title": "Start", "task_type": "echo", "payload": {"step": 1}},
            {"id": "finish", "title": "Finish", "task_type": "sum", "payload": {"numbers": [2, 3]}},
        ],
        "edges": [{"source": "start", "target": "finish"}],
    }


def test_cycle_validation_returns_422(client):
    body = graph_body()
    body["edges"] = [{"source": "start", "target": "finish"}, {"source": "finish", "target": "start"}]
    response = client.post("/api/workflows", json=body)
    assert response.status_code == 422
    assert "Cycle detected" in response.json()["detail"]


def test_workflow_dependencies_execute_in_order(client):
    created = client.post("/api/workflows", json=graph_body())
    assert created.status_code == 201, created.text
    workflow = created.json()
    run_res = client.post(f"/api/workflows/{workflow['id']}/runs")
    assert run_res.status_code == 201, run_res.text
    run = run_res.json()
    assert run["status"] == "running"
    assert run["node_states"]["start"]["status"] == "queued"
    assert run["node_states"]["finish"]["status"] == "pending"
    assert run_once("test-worker") is True
    with SessionLocal() as db:
        jobs = db.query(Job).filter(Job.workflow_run_id == run["id"]).all()
        assert len(jobs) == 2
        first = next(j for j in jobs if j.workflow_node_id == "start")
        second = next(j for j in jobs if j.workflow_node_id == "finish")
        assert first.status == "succeeded"
        assert second.status == "queued"
    assert run_once("test-worker") is True
    status = client.get(f"/api/workflows/runs/{run['id']}")
    assert status.status_code == 200
    assert status.json()["status"] == "succeeded"
    assert status.json()["node_states"]["finish"]["status"] == "succeeded"


def test_workflow_missing_dependency_is_rejected(client):
    body = graph_body()
    body["edges"] = [{"source": "start", "target": "missing"}]
    assert client.post("/api/workflows", json=body).status_code == 422
