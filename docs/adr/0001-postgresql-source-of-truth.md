# ADR-0001: PostgreSQL is the queue of record

- **Status:** Accepted for MVP
- **Context:** Jobs must survive API/worker restarts and be inspectable in a single transaction model.
- **Decision:** Persist jobs and attempts in PostgreSQL and claim with row locks plus `SKIP LOCKED`. Redis remains reserved but is not on the claim path.
- **Consequences:** Simple consistency and durable inspection; database contention and queue query plans must be load-tested. A future broker can be considered with measured evidence and an outbox/migration plan.
