# QueueForge Nexus

QueueForge Nexus is a full-stack portfolio MVP for durable background jobs and dependency-aware workflows. This repository includes a FastAPI control plane, a PostgreSQL-backed worker engine, a standalone operations console, migrations, Docker Compose, and automated tests.

**Status: runnable MVP, not yet a hardened production service.** Core job persistence, worker execution, retries, lease recovery, API-key authentication, idempotency, and DAG workflows are implemented. Real deployment, HTTPS, a managed secrets store, load/fault testing, and independent security review are still required before handling important customer work.

## What's implemented

- Durable REST API for creating, listing, filtering, reading, retrying, and cancelling jobs.
- PostgreSQL schema with Alembic migration; SQLite works for local development and tests.
- Separate worker process, prioritized queue claims, lease renewal, fencing by attempt number, lease-expiry recovery, retry backoff, attempt history, and dead-letter state.
- Four safe example task handlers: `echo`, `sum`, `sleep`, `flaky`. Unknown handler names fail into a terminal state rather than executing arbitrary code.
- Tenant-scoped jobs, idempotency keys, monthly quota enforcement, API keys stored as salted PBKDF2 hashes, scope checks, key creation/revocation, and tenant pause checks.
- DAG validation and persisted workflow runs. A downstream task is released when every dependency succeeds; failed dependencies move the workflow into a terminal failed state.
- Liveness/readiness probes, dashboard summary, worker listing, audit-event list, request correlation IDs, and aggregate Prometheus metrics behind a platform `admin` scope.
- Fail-closed production configuration checks (`APP_ENV=production` requires authentication, a long bootstrap key, PostgreSQL, migration-managed schemas, and explicit CORS origins).
- Nginx request-size and per-IP burst limits as an edge guard; public deployments still need a trusted TLS ingress and preferably an API-key-aware distributed limiter.
- GitHub Actions CI, coverage reporting, security-scan steps, architecture and threat-model docs, ADRs, a repeatable interview demo, and a load-test script.
- Operations console based on the saved QueueForge Nexus design. In Settings, **Live backend connection** accepts an API URL and optional bearer token; on successful connection, jobs are fetched from the API and job creation/API Explorer requests can use the real backend. The token is kept in tab session storage only.
- Docker Compose services for API, worker, PostgreSQL, Redis (reserved for a future increment), and Nginx frontend proxy.

## Quick start: Docker Compose

Requirements: Docker Desktop or Docker Engine with the Compose plugin.

```bash
cp .env.example .env
# Edit .env. For local evaluation, AUTH_ENABLED=false is convenient.
# Before any network/shared deployment, set AUTH_ENABLED=true and a unique
# BOOTSTRAP_API_KEY of 32+ random characters and configure TLS/secrets.
docker compose up --build
```

Open:

- Console: http://localhost:5173
- API liveness: http://localhost:8000/api/health/live
- API readiness: http://localhost:8000/api/health/ready
- Interactive API docs: http://localhost:8000/docs
- OpenAPI schema: http://localhost:8000/openapi.json

The Compose host ports bind to `127.0.0.1` so the development stack is not automatically exposed to your LAN. The app uses a PostgreSQL named volume. Stop with `Ctrl+C`, then `docker compose down`. To also delete the local database, use `docker compose down -v` (destructive; it deletes stored jobs).

> The default Compose password in `.env.example` is development-only. Change it; do not reuse it in any shared environment. The API default is unauthenticated for easy local evaluation. Do not expose that configuration to the public internet.

## Quick start: without Docker

Requirements: Python 3.11+ (tested here with Python 3.13) and pip.

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd backend
# activate the same virtual environment
python -m app.worker --worker-id worker-local-1 --poll 0.7
```

The API defaults to `sqlite:///./queueforge.db` for local convenience. Tables are created when the app starts. To use PostgreSQL, set `DATABASE_URL`, for example `postgresql+psycopg://user:password@localhost:5432/queueforge`, and run `alembic upgrade head` from `backend/` before starting the API.

### Try a job

With the worker running:

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-order-58317' \
  -d '{"task_type":"sum","queue":"critical","priority":8,"payload":{"numbers":[3,4,5]},"max_attempts":3}'
```

Then inspect the returned `id` with `GET /api/jobs/{id}`. Example task types:

- `echo`: returns the payload.
- `sum`: adds a non-empty array of numeric `payload.numbers`.
- `sleep`: sleeps for up to `MAX_SLEEP_SECONDS` (default 15).
- `flaky`: fails for the first `payload.fail_times` attempts, then succeeds, to exercise retries.

### Connect the console to the API

When using the Compose frontend, visit http://localhost:5173, open **Settings → Live backend connection**, leave the base URL as `/api` to use the same-origin Nginx proxy, and choose **Connect & sync jobs**. With local development authentication disabled, the key field can remain blank. If authentication is enabled, use a valid API key with appropriate scopes. For a separately hosted API, enter its full HTTPS base URL, allow the frontend origin in the backend's `CORS_ORIGINS`, and add the exact API origin to the frontend CSP `connect-src` directive.

The connector verifies `/health` and then requires an authorized `/jobs` response before declaring the UI connected. It does not silently treat sample data as live. When connected, these console areas use the real API: Jobs (list/create/retry/cancel/duplicate, real attempt history), Workflows (**Run** saves the graph as a versioned workflow and starts a durable run executed by real workers), Workers, Audit Log, Security (API keys: create/revoke), Tenants (read-only current tenant), API Explorer, and the Overview tiles (jobs, success rate, p95 runtime, active workers). The console polls every 5 s while connected. **Still illustrative even when connected:** throughput chart, system-health panel, Observability signals, Integrations/webhooks, Engineering Lab, pricing. Worker pause/drain/restart and tenant create/pause are simulated in demo mode only — the API has no such endpoints yet.

## Enable API-key authentication

For local API testing without Compose:

```bash
cd backend
export AUTH_ENABLED=true
export BOOTSTRAP_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
uvicorn app.main:app --port 8000
```

Save the generated key in a password manager or secret manager before leaving the terminal. It is the environment bootstrap administrator key; only a hash is stored in the database. Requests must include:

```http
Authorization: Bearer <your-key>
```

When using Compose, set `AUTH_ENABLED=true` and `BOOTSTRAP_API_KEY` in `.env` before starting. Restarting the API updates the bootstrap key hash to the value in the environment, so rotate that secret deliberately. Do not put secrets in source files, screenshots, tickets, or Git.

Create a limited API key from the authenticated API:

```bash
curl -X POST http://localhost:8000/api/keys \
  -H "Authorization: Bearer $BOOTSTRAP_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"name":"read-only monitor","scopes":["jobs:read","workers:read","audit:read"]}'
```

The raw token is returned only in the creation response. Store it safely; subsequent key listings never return raw tokens.

## REST API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Database readiness and API mode |
| `GET` | `/api/dashboard` | Tenant-scoped counts and recent jobs |
| `GET` / `POST` | `/api/jobs` | Filter/list and enqueue durable jobs |
| `GET` | `/api/jobs/{id}` | Job data and attempt history |
| `POST` | `/api/jobs/{id}/retry` | Requeue terminal dead/cancelled job |
| `POST` | `/api/jobs/{id}/cancel` | Cancel a queued job |
| `GET` | `/api/workers` | Worker heartbeats and current assignment |
| `GET` / `POST` | `/api/workflows` | List/create versioned DAG definitions |
| `POST` | `/api/workflows/validate` | Validate workflow nodes and edges |
| `POST` | `/api/workflows/{id}/runs` | Start a durable workflow run |
| `GET` | `/api/workflows/runs/{id}` | Inspect workflow and node states |
| `GET` | `/api/audit` | Tenant-scoped operator/audit events |
| `GET` | `/api/tenants/current` | Authenticated tenant details |
| `GET` / `POST` | `/api/keys` | List/create scoped API keys (raw token shown once) |
| `POST` | `/api/keys/{id}/revoke` | Revoke a key |

Browse `/docs` for request schemas and response examples. Scope requirements are documented in the OpenAPI descriptions and enforced by API dependencies.

## Tests, coverage, and CI

```bash
# from the repository root
make test
make lint
make security
make compose-config
```

The suite exercises health/request IDs/metrics, job CRUD, exact idempotency replay and conflicting key reuse, cancellation states, cross-tenant reads, scope checks, key revocation, cycle rejection, workflow execution order, retry/dead-letter behavior, and stale-worker attempt fencing. It uses SQLite for speed, so it does not substitute for PostgreSQL locking tests. The current local run (2026-10-25) passed **22 tests with 80% coverage (branch-aware)**; the CI lint selection and Bandit (`bandit -q -r app scripts`, exit code 0) were also run locally. `backend/e2e/e2e_check.py` additionally starts a real API and real worker processes and checks 54 behaviours over HTTP (retries, dead-letter, DAG order, 4-worker contention, `kill -9` lease recovery, auth/scopes/revocation, quota, paused tenant, production fail-closed) — 54/54 passed on SQLite and on PostgreSQL 16 (8 workers x 300 jobs).

`backend/scripts/load_test.py` can create a bounded number of jobs and report HTTP outcomes plus p50/p95/p99 request latency. Only run it against systems you own. Do not quote benchmark numbers without recording hardware, database settings, payload shape, worker count, and test duration.

## Engineering docs and placement demo

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): component diagram, consistency guarantees, and failure cases.
- [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md): security boundaries, controls, residual risks, and deployment gates.
- [`docs/adr/`](docs/adr/): architecture decision records and their trade-offs.
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md): a repeatable seven-minute API/worker/workflow/security demonstration.
- [`docs/VALIDATION.md`](docs/VALIDATION.md): recorded checks, browser-smoke results, and explicit environment limitations.
- [`PORTFOLIO.md`](PORTFOLIO.md): truthful resume bullets, interview story, and a skills checklist for placement preparation.

## Architecture & state transitions

```text
Operations UI ──HTTP──> FastAPI control plane ──> PostgreSQL
                                                  ▲       │
                                                  │       └── jobs + attempts + workflows + audit
                                                  │
                       Worker claim (FOR UPDATE SKIP LOCKED where supported)
                            │
                    lease + heartbeat + fencing
                            │
                 registered task handler (allow-list)
                            │
              result / retry-backoff / dead-letter
```

PostgreSQL is the source of truth for queued work. Workers claim rows transactionally, renew a lease while running, and can only finish the attempt they still own. This prevents an expired/stale attempt from overwriting a newer attempt; it does **not** guarantee exactly-once external side effects. Task handlers that touch third-party services must implement application-level idempotency/outbox patterns.

The current worker has a single execution slot per worker process. Scale by running more worker processes, then validate contention and fairness under PostgreSQL. Redis is included in Compose but is **not** used for job correctness in this iteration.

## Before real production use

This repository intentionally stops short of claiming full production readiness. Complete and verify these items in the target environment:

1. Set `APP_ENV=production`, `AUTH_ENABLED=true`, a unique `BOOTSTRAP_API_KEY` of at least 32 characters, a PostgreSQL URL, `AUTO_CREATE_SCHEMA=false`, and explicit trusted CORS origins. The application now fails fast if those requirements are not met.
2. Terminate TLS at a trusted ingress, restrict network exposure, configure CORS narrowly, and store database/API secrets in a managed secret service.
3. Review auth bootstrap/rotation, add user/SSO sessions and formal RBAC, enforce tenant ownership on all resource classes, and test isolation adversarially.
4. Add database connection pooling limits, backup/PITR recovery drills, retention/archival, migration rollback procedures, API-key-aware distributed rate limiting, and quota fairness/concurrency policies.
5. Add real webhook delivery with signatures, deduplication, retries, and delivery logs; connect OpenTelemetry, dashboards, and alerting. Prometheus request/job metrics are present but still need deployment-specific scrape configuration.
6. Add PostgreSQL concurrency tests, load/soak tests, crash/restart and stale-lease fault injection, dependency-vulnerability scanning, SBOM/image scanning, and an independent security review.
7. Define SLOs, on-call and incident runbooks, tenant deletion/export policy, data privacy requirements, and capacity/queue fairness objectives.

**Do not use this MVP for high-value or sensitive workloads until those gates have been completed and independently verified.**
