# Operations runbook (MVP)

This runbook is a starting point for local/pre-production operations. Adapt it to the real hosting provider, alerting path, owners, and recovery objectives before launch.

## API readiness is failing

1. Check `GET /api/health/live`. If it fails, inspect container/process logs and recent deploys.
2. Check `GET /api/health/ready`. A 503 points to database connectivity/readiness; do not route traffic until readiness is restored.
3. Check PostgreSQL service health, disk space, connection limits, and authentication configuration.
4. Verify migrations are at the expected Alembic head. Do not manually mutate production tables to bypass a failed migration.
5. Roll back the application image if the last release introduced the fault; only roll back schema if a tested backward-compatible procedure exists.

## Queue lag is increasing

1. Query the job list for counts by status and queue. Inspect `available_at`, creation age, and priority distribution.
2. Check worker heartbeats at `GET /api/workers` using a key with `workers:read`.
3. Check worker logs for database errors, unknown task types, retry loops, and task timeouts.
4. Scale worker processes only after checking DB connection limits and queue-claim contention.
5. If high-priority work starves lower-priority jobs, record the workload mix and add a measured fairness/aging policy before changing priority behavior.

## Dead-letter growth or retries spike

1. Inspect individual job attempt history via `GET /api/jobs/{id}`.
2. Group errors by task type and dependency; avoid retry storms for deterministic input/config errors.
3. Pause external side effects at the task-handler level if retries could charge, notify, or create duplicate third-party state.
4. Correct the cause, then retry a small sample of dead jobs with an operator audit reason.
5. Verify queue lag and error rates return to baseline before declaring recovery.

## Worker lease recovery

1. Check worker heartbeat timestamp, current job ID, and lease expiry.
2. A missed lease may result in the job being retried; the queue provides at-least-once execution.
3. Confirm external handlers use idempotency keys or downstream deduplication.
4. Review attempt history and the `job.lease_recovered` audit event. A stale worker completion must not replace a newer attempt's result.

## Credential exposure

1. Revoke the affected key immediately via `POST /api/keys/{id}/revoke` using a separate admin key.
2. Rotate the bootstrap credential in the secret manager and restart the API deliberately; the bootstrap hash is refreshed from environment configuration at startup.
3. Review API and audit records for the incident window. Avoid logging bearer tokens or request payload secrets.
4. Reissue least-privilege keys and validate their scopes with negative tests.

## Before closing an incident

Capture request IDs, timestamps, affected tenants, queue/status counts, changes made, recovery verification, follow-up actions, and a blameless root-cause note. Never record raw API tokens or sensitive payloads in the incident report.
