# Local validation record

**Snapshot date:** 2026-10-25 (supersedes the 2026-10-24 record). Purpose: record what was actually verified. This is not a production certification.

## Passed locally (SQLite, Python 3.12, Chromium 141)

- `pytest -q --cov=app`: **22 passed**, 80% coverage (branch-aware). `ruff check app tests scripts --select E9,F63,F7,F82` and `bandit -q -r app scripts` both exit 0 (the previous revision failed Bandit on B112).
- `python e2e/e2e_check.py` (real API + worker processes over HTTP): **54/54** — idempotency replay/conflict, retry/backoff/dead-letter, manual retry, cancel, DAG order (diamond), failed-parent blocking, 4 workers x 60 jobs with no duplicate execution, `kill -9` mid-job lease recovery (attempts `lost` then `succeeded`), SIGTERM -> offline, auth/scopes/key revoke, key listing never leaks secrets, quota 429, paused tenant 423, production config fail-closed.
- Browser (Playwright/Chromium, real API + worker behind an nginx-equivalent proxy):
  - Live mode UI<->backend: **27/27** (connect, create/execute, retry, cancel, duplicate, real attempt history, workflow runs, workers, tenant, audit, keys, API Explorer, dashboard tiles, browser timezone Asia/Kolkata).
  - Demo mode semantics, responsive overflow on all 14 tabs at 390 px and 768 px, wrong key / limited-scope key handling: **28/28**.
  - Exhaustive click audit of every visible control on every tab, two levels deep (including dialogs/drawers): 0 dead controls, 0 JavaScript errors.

## Defects found and fixed in this revision

See `CHANGELOG.md`.

## PostgreSQL and web-server validation (added 2026-10-26)

- PostgreSQL 16: `alembic upgrade head` applies the migration (9 tables) and `alembic check` reports no drift between models and migration.
- `pytest` on PostgreSQL: **22/22** (one test needed a `flush()` because PostgreSQL enforces the `jobs.tenant_id` foreign key; the old test would have turned the CI run red because CI tests on PostgreSQL).
- `E2E_DATABASE_URL=postgresql+psycopg://... E2E_JOBS=300 E2E_WORKERS=8 python e2e/e2e_check.py`: **54/54**, including 8 workers x 300 jobs with `SKIP LOCKED` contention and zero duplicate attempts, and `kill -9` lease recovery.
- The exact CI sequence (alembic, ruff selection, pytest with coverage, bandit) was replayed against a fresh PostgreSQL database with the CI environment variables: all green (22 tests, 80% coverage).
- Real nginx (1.24) with `frontend/nginx.conf` and exactly the files the frontend Dockerfile copies: correct MIME types, security headers, `/api` and `/docs` proxying; browser live suite **27/27** through it against the PostgreSQL-backed API.

## Not verified in this environment

- Docker itself: `docker compose config`, `docker compose build/up` and the built images were **not** run (no Docker in the sandbox). Compose and Dockerfile references (COPY sources, health endpoints, `depends_on` chain) were reviewed statically. Run `docker compose up --build` once before relying on it. The image uses nginx 1.27; testing used 1.24 with the same config.
- GitHub Actions was not executed; its commands were replayed locally.
- Load/soak tests, TLS, backups, alerting and an independent security review remain release gates.
- One unexplained, non-reproduced 15 s HTTP read timeout occurred once in a test harness run that deliberately froze (SIGSTOP) a worker on SQLite; it did not recur and logs showed no lock errors.
