# QueueForge Nexus — placement portfolio brief

Use this as a project brief to prepare an honest resume entry and technical discussion. Customize the bullets only after personally reproducing the behaviors and understanding the implementation.

## Project summary

**QueueForge Nexus | Durable Job Orchestration Platform**  
Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Docker Compose, pytest, Prometheus, Nginx

Designed and implemented a job orchestration backend that separates request acceptance from worker execution. The system persists jobs and attempt history, validates workflow DAGs, uses expiring leases for worker recovery, and exposes a control-plane UI for job operations.

## Resume bullets (choose 3–4)

- Built a FastAPI + PostgreSQL job control plane with validated REST contracts, Alembic migrations, scoped API-key authorization, tenant-bound queries, monthly quota checks, and audit events.
- Implemented a lease-based worker engine with prioritized `SKIP LOCKED` claims, heartbeats, attempt history, capped exponential retries, dead-letter handling, and worker/attempt fencing to reject stale completion.
- Developed a dependency-aware workflow engine with topological validation, cycle/duplicate-edge rejection, versioned graph snapshots, and persisted node states for workflow runs.
- Hardened request semantics with idempotency-key replay for identical payloads, HTTP 409 for key reuse with a different request, bounded payloads, request IDs, separate liveness/readiness probes, and low-cardinality Prometheus metrics.
- Added tenant-scoped API keys stored as salted PBKDF2 hashes, scope enforcement, revocation, production configuration fail-fast checks, Nginx request-size/rate controls, and automated security/coverage checks in CI.
- Added 22 automated tests (plus a 54-check real-process end-to-end script) covering API behavior, tenant isolation, global-scope delegation, idempotency conflicts, workflow dependencies and failure/cancel/retry semantics, manual-retry attempt history, retries, stale-worker fencing, and worker shutdown; the recorded local run reported 80% coverage with branch coverage enabled.

Do not claim a throughput number until you run `backend/scripts/load_test.py` against a documented environment. Do not describe the project as production-deployed until you deploy it, enable auth/TLS, and verify the production launch gates.

## 90-second interview narrative

**Problem:** Background work should not be tied to the lifetime of an HTTP request. It must survive process restarts, expose state and attempts, recover abandoned work, and express dependencies.

**Design:** The API writes jobs and audit events transactionally. PostgreSQL is the source of truth. Workers claim queued rows under row locks, increment an attempt number, and set a lease. While executing, they renew the lease. Completion checks both worker ID and attempt number, fencing off an old worker if a job was reclaimed. Transient failures get bounded exponential backoff; permanent/exhausted failures become dead-letter jobs.

**Workflow layer:** A workflow is a DAG. Validation rejects unknown nodes, duplicate edges, self-links, and cycles. A run keeps a graph snapshot and enqueues a child only when every parent succeeded.

**Trade-off:** This delivers at-least-once execution, not exactly-once side effects. If a handler calls an external API and crashes before committing success, that side effect may happen again. Downstream operations must accept an idempotency key or use deduplication/outbox patterns.

**What is not finished:** Full production SSO/RBAC, distributed rate limiting, actual webhook dispatch, OpenTelemetry and paging alerts, PostgreSQL race/soak tests, backups/restore drills, and independent security review.

## Questions to practice answering

1. Why is PostgreSQL the source of truth instead of Redis? What are the contention trade-offs?
2. What does `FOR UPDATE SKIP LOCKED` provide, and what would change on SQLite?
3. Why is a lease alone insufficient without fencing by attempt number?
4. How do you avoid duplicate jobs after a client timeout? What happens if a key is reused with another body?
5. Why is exactly-once execution hard when side effects cross a database boundary?
6. How do workflow runs behave when one parent fails? How do you prove cycle rejection?
7. How are API keys stored, scoped, revoked, and prevented from crossing tenant boundaries?
8. Which metrics are low-cardinality, and why should job IDs not be Prometheus labels?
9. What tests would you add for two workers racing for the same queue under PostgreSQL?
10. What must change before you would trust the service with billing or customer data?

## Placement execution plan (4 weeks)

- **Week 1:** Run every demo from a clean checkout. Draw the data model and state transitions by hand; understand every worker/lease path.
- **Week 2:** Add PostgreSQL integration and concurrency tests. Reproduce stale lease recovery and same-key/different-body behavior.
- **Week 3:** Deploy to a low-cost test environment with TLS and auth. Configure real metrics and at least one alert. Document deployment rollback.
- **Week 4:** Run a measured load test, record p50/p95/p99 and environment details, conduct a security-negative test pass, and rehearse the seven-minute demo.

A strong interview outcome comes from explaining why choices were made, showing failure cases, and discussing trade-offs—not from claiming every checkbox is production-ready.
