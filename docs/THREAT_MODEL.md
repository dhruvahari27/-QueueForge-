# Threat model and security posture

## Assets

Job payloads/results, worker state, workflow definitions, tenant configuration, API credentials, and the operator audit trail.

## Trust boundaries

1. Browser/SDK → API network boundary.
2. API key → server-side scope and tenant boundary.
3. API → database transaction boundary.
4. Worker → untrusted task payload and task implementation boundary.
5. Worker → any future external side-effect target.

## Implemented controls

- API keys are random bearer values; only a salted PBKDF2 hash is stored, and a raw key is returned once when created.
- Request handlers derive the tenant from the validated principal; job and workflow queries filter by that tenant. The client cannot select an arbitrary `X-Tenant-ID` header.
- Scope checks protect writes, worker reads, audit, and key management. Only a platform-admin key may grant `workers:read`; tenant key managers cannot delegate service-wide worker inventory access.
- Job payload size is checked after model validation and request `Content-Length` receives an early boundary check.
- Production startup rejects disabled auth, weak/missing bootstrap keys, SQLite, auto-created production schemas, and wildcard CORS.
- Security headers, request IDs, audit events, and API key revocation are present.
- Prometheus metrics avoid sensitive/high-cardinality labels and require platform `admin` scope because counts are service-wide. Tenant-scoped `audit:read` cannot access these aggregate service metrics.

## Required before public production

- Terminate TLS at a trusted reverse proxy, restrict network ingress, use managed secrets, and replace all development passwords.
- Enable `APP_ENV=production`, `AUTH_ENABLED=true`, a long random `BOOTSTRAP_API_KEY`, explicit origins, and Alembic-only schema updates.
- Add per-key distributed rate limits, key expiry/rotation policy, secret access alerts, and administrative RBAC beyond the current scopes.
- Add SSRF protection and outbound DNS/IP controls before accepting webhook URLs; the current MVP intentionally does not send webhook requests.
- Test tenant isolation under all list/detail/export/workflow/worker routes, not just a representative case. Add a PostgreSQL integration test job in CI.
- Set data retention, encryption-at-rest requirements, backup/restore RTO/RPO, audit retention, and incident response processes.
- Threat-model task handlers: they must not evaluate arbitrary code, trust payload paths, or perform unbounded CPU/network/file operations.

## Known risks / honest status

The development auth bypass is intentional for local smoke tests. It is not suitable for a shared machine or the public internet. The simple queue is at-least-once and may execute a task again after a lease expires. Downstream side effects therefore require idempotency or deduplication. No independent security audit has been performed.
