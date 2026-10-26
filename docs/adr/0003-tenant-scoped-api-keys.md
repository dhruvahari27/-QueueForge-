# ADR-0003: Scoped tenant-bound API keys

- **Status:** Accepted for MVP
- **Context:** Automation needs credentials with limited permissions while tenant data must remain isolated.
- **Decision:** Bearer tokens are random, only their salted hash is stored, scopes are validated on handlers, and the tenant is derived from the key record.
- **Consequences:** Keys can be revoked and read/write access separated. Expiry/rotation, a richer role model, distributed limits, and external identity are separate production hardening tasks.
