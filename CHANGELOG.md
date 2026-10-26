# Changelog — validation pass 2026-10-25

## Backend
- **Fixed (critical): manual retry wedged the queue.** `POST /jobs/{id}/retry` reset `attempts_count` to 0 but kept old `job_attempts` rows, so the next claim violated `uq_job_attempt_number`; the failing job stayed at the head of the queue and starved every job behind it. Retry now keeps the attempt history and grants a fresh budget (`max_attempts += previous max`).
- **Fixed: cancelling a queued workflow job left the run `running` forever.** The run is now settled (`cancelled`, downstream `blocked`).
- **Fixed: retrying a failed/cancelled workflow node did not resume the run.** The run is revived and blocked nodes return to `pending`.
- **Fixed:** results of sibling branches that finish after a run already ended are now recorded in `node_states`.
- **Fixed:** starting a workflow run now enforces paused-tenant (423) and monthly quota (429, counting all nodes); previously both were bypassed.
- **Fixed:** Bandit B112 (silent `except/continue` in the lease heartbeat) failed the CI security step; it now logs a warning.
- 4 regression tests added (`tests/test_regressions.py`); `backend/e2e/e2e_check.py` added.

## Frontend
- **Fixed: Docker image omitted `console-actions.js`** (served as HTML → `Unexpected token '<'`, refresh/export/live-retry controls undefined). Dockerfile now copies all scripts.
- **New `live-wiring.js`:** in live mode, Retry, workflow Run, Workers, Audit Log, API keys (create/revoke, token shown once), Tenant and Overview tiles use the real API; real per-attempt history in the job drawer; 5 s polling.
- **Fixed:** "Copy JSON" threw `ReferenceError: j is not defined`; copy buttons now fall back when the Clipboard API is unavailable and no longer report false success.
- **Fixed:** timestamps without a timezone (SQLite) were parsed as local time ("5h ago" for a job created seconds ago in IST).
- **Fixed:** "Selected workflow" label showed the selected node's title.
- **Fixed:** 5 px horizontal overflow of the page heading at tablet width.

## Known gaps (not changed)
- No API for tenant create/update/pause or worker pause/drain; those controls are demo-only.
- Webhook delivery, OpenTelemetry, distributed rate limiting, SSO are not implemented (see README gates).
- The `/` shortcut opens the command palette instead of focusing job search.

## Visual refresh
- Calm animated aurora background, glass panels, 20px rounded cards, pill buttons with lift/glow/shimmer hover, gradient active nav, focus rings.
- Five colour themes (Aurora, Ocean, Emerald, Sunset, Rose) plus an auto-cycle mode in the top bar; choice is remembered. Lives in `frontend/theme.css` and `frontend/theme.js` (also copied by the Dockerfile); no logic changed. Verified in dark and light mode; theme dots are hidden below 1100 px to avoid tablet overflow.

## Final pass (2026-10-26)
- Fixed the page heading label: Jobs and every other core tab showed a stale "SYSTEM OVERVIEW / ILLUSTRATIVE DATA" (or the last platform tab's name). Core tabs now show `QUEUEFORGE NEXUS / <TAB>`; Overview shows `LIVE DATA` when connected.
- Fixed `tests/test_security.py` for PostgreSQL (foreign key ordering); CI runs tests on PostgreSQL so this would have failed the first pipeline run.
- `backend/e2e/e2e_check.py` now runs on SQLite or PostgreSQL (`E2E_DATABASE_URL`, `E2E_JOBS`, `E2E_WORKERS`).
- Verified on PostgreSQL 16 and real nginx; see `docs/VALIDATION.md`.
