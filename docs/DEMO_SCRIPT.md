# 7-minute engineering demo

## 0:00–0:45 — Problem and model

Explain that the service separates accepting work from executing it. The database is the source of truth; a worker claims a queued job, holds a lease, writes an attempt, and commits a terminal state.

## 0:45–1:45 — Idempotent API submission

Start Compose and open `/docs`. Create an `echo` job with `Idempotency-Key: demo-order-58317`; submit the identical request again. Show the same job ID and a replay response. Reuse the key with a different payload and show HTTP 409.

## 1:45–2:45 — Execution and attempts

With the worker running, inspect `/api/jobs/{id}` until status becomes `succeeded`. Show worker ID, timestamps, and attempt history.

## 2:45–3:45 — Retry semantics

Create a `flaky` job with `{"fail_times": 1}` and `max_attempts: 3`. Explain capped exponential backoff, the failed attempt row, and why retries imply at-least-once semantics.

## 3:45–4:45 — Workflow DAG

Create a two-node workflow and run it. Inspect node states before and after each worker execution. Then attempt a cycle and show that validation rejects it.

## 4:45–5:45 — Security boundary

Run with `AUTH_ENABLED=true`, create two tenants/keys in a disposable test DB (or run the security test), and prove that a read-only key cannot create jobs and that tenant A cannot read tenant B's job. Do not demo the development bypass as a security feature.

## 5:45–6:30 — Observability

Use `/api/health/live`, `/api/health/ready`, the `X-Request-ID` response header, and `/api/metrics` with the appropriate key scope. Discuss low-cardinality metric labels.

## 6:30–7:00 — Trade-offs and next steps

State clearly: worker concurrency is one task per process; SQLite tests do not prove PostgreSQL lock behavior; external webhook delivery, distributed rate limiting, TLS, deployed alerts and disaster recovery remain to be built and tested.
