"""DAG validation and workflow scheduling helpers."""
from __future__ import annotations

from collections import defaultdict, deque
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Job, WorkflowRun, utcnow


class DAGError(ValueError):
    pass


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not nodes:
        raise DAGError("A workflow must contain at least one node")
    if len(nodes) > 250 or len(edges) > 1000:
        raise DAGError("Workflow graph exceeds size limits")
    ids = [str(n.get("id", "")) for n in nodes]
    if any(not x for x in ids):
        raise DAGError("Every node needs a non-empty id")
    if len(set(ids)) != len(ids):
        raise DAGError("Node IDs must be unique")
    known = set(ids)
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {x: 0 for x in ids}
    seen_edges: set[tuple[str, str]] = set()
    for e in edges:
        src, dst = str(e.get("source", "")), str(e.get("target", ""))
        if src not in known or dst not in known:
            raise DAGError(f"Edge references an unknown node: {src} -> {dst}")
        if src == dst:
            raise DAGError("Self-links are not allowed")
        if (src, dst) in seen_edges:
            raise DAGError(f"Duplicate edge: {src} -> {dst}")
        seen_edges.add((src, dst))
        outgoing[src].append(dst)
        indegree[dst] += 1
    queue = deque([x for x, degree in indegree.items() if degree == 0])
    order: list[str] = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for nxt in outgoing[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(ids):
        raise DAGError("Cycle detected; workflow definitions must be directed acyclic graphs")
    return {"valid": True, "node_count": len(nodes), "edge_count": len(edges), "topological_order": order}


def _node_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["id"]: n for n in graph["nodes"]}


def _create_workflow_job(db: Session, run: WorkflowRun, node: dict[str, Any]) -> Job:
    job_id = "jf_" + secrets.token_hex(7)
    job = Job(
        id=job_id, tenant_id=run.tenant_id, task_type=node["task_type"],
        queue=node.get("queue", "workflows"), status="queued", priority=node.get("priority", 5),
        payload=node.get("payload") or {}, max_attempts=node.get("max_attempts", 3),
        attempts_count=0, available_at=utcnow(), workflow_run_id=run.id, workflow_node_id=node["id"],
    )
    db.add(job)
    return job


def start_workflow_run(db: Session, workflow, tenant_id: str) -> WorkflowRun:
    graph = workflow.graph
    validate_graph(graph)
    nodes = _node_map(graph)
    incoming = {node_id: 0 for node_id in nodes}
    for edge in graph["edges"]:
        incoming[edge["target"]] += 1
    states = {node_id: {"status": "pending", "job_id": None} for node_id in nodes}
    run = WorkflowRun(id="wr_" + secrets.token_hex(8), tenant_id=tenant_id, workflow_id=workflow.id, workflow_name=workflow.name, workflow_version=workflow.version, graph=graph, node_states={}, status="running")
    db.add(run)
    db.flush()
    for node_id, degree in incoming.items():
        if degree == 0:
            job = _create_workflow_job(db, run, nodes[node_id])
            states[node_id] = {"status": "queued", "job_id": job.id}
    run.node_states = {key: dict(value) for key, value in states.items()}
    return run


def _terminal_node_state(job: Job) -> dict[str, Any]:
    if job.status == "succeeded":
        return {"status": "succeeded", "job_id": job.id}
    if job.status == "cancelled":
        return {"status": "cancelled", "job_id": job.id, "error": job.error}
    return {"status": "failed", "job_id": job.id, "error": job.error}


def settle_workflow_job(db: Session, job: Job) -> None:
    """Advance a workflow run after one of its jobs reached succeeded / dead / cancelled."""
    if not job.workflow_run_id or not job.workflow_node_id:
        return
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == job.workflow_run_id).with_for_update())
    if run is None:
        return
    states = dict(run.node_states or {})
    node_id = job.workflow_node_id
    if node_id not in states:
        if run.status == "running":
            run.status = "failed"
            run.finished_at = utcnow()
        return
    if run.status != "running":
        # A sibling branch finishing after the run already ended: record its outcome, schedule nothing.
        if job.status in ("succeeded", "dead", "cancelled"):
            states[node_id] = _terminal_node_state(job)
            run.node_states = states
        return
    if job.status in ("dead", "cancelled"):
        states[node_id] = _terminal_node_state(job)
        run.status = "failed" if job.status == "dead" else "cancelled"
        run.finished_at = utcnow()
        reason = "upstream dependency failed" if job.status == "dead" else "upstream dependency cancelled"
        # Tasks which can no longer run are explicitly marked blocked.
        for remaining, item in states.items():
            if item.get("status") == "pending":
                states[remaining] = {"status": "blocked", "job_id": None, "reason": reason}
        run.node_states = states
        return
    if job.status == "succeeded":
        states[node_id] = {"status": "succeeded", "job_id": job.id}
    graph = run.graph
    nodes = _node_map(graph)
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in graph["edges"]:
        incoming[edge["target"]].append(edge["source"])
    # A downstream node is enqueued once all of its upstream nodes succeeded.
    for candidate_id, item in list(states.items()):
        if item.get("status") != "pending":
            continue
        parents = incoming[candidate_id]
        if all(states[p].get("status") == "succeeded" for p in parents):
            child_job = _create_workflow_job(db, run, nodes[candidate_id])
            states[candidate_id] = {"status": "queued", "job_id": child_job.id}
    if states and all(item.get("status") == "succeeded" for item in states.values()):
        run.status = "succeeded"
        run.finished_at = utcnow()
    run.node_states = states


def reopen_workflow_job(db: Session, job: Job) -> None:
    """A failed/cancelled workflow job was manually retried: put its node back and revive the run."""
    if not job.workflow_run_id or not job.workflow_node_id:
        return
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == job.workflow_run_id).with_for_update())
    if run is None or run.status == "succeeded":
        return
    states = dict(run.node_states or {})
    node_id = job.workflow_node_id
    if node_id not in states:
        return
    states[node_id] = {"status": "queued", "job_id": job.id}
    others_bad = any(v.get("status") in ("failed", "cancelled") for k, v in states.items() if k != node_id)
    if run.status in ("failed", "cancelled") and not others_bad:
        run.status = "running"
        run.finished_at = None
        for key, item in list(states.items()):
            if item.get("status") == "blocked":
                states[key] = {"status": "pending", "job_id": None}
    run.node_states = states
