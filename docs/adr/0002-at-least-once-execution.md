# ADR-0002: Lease-based at-least-once execution

- **Status:** Accepted for MVP
- **Context:** A worker may die between claim and completion, and the platform must recover abandoned jobs.
- **Decision:** Jobs have expiring leases and monotonic attempt numbers. Completion is accepted only for the current worker and attempt.
- **Consequences:** Stale completions are fenced out and expired jobs can be retried. A side effect may happen twice if the worker dies after the side effect but before committing success; handlers and downstream APIs must therefore be idempotent.
