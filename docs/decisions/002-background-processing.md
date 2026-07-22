# ADR-002 — Local background processing

## Status

Accepted

## Decision

Use a SQLite-backed local task queue and a separate worker process.

- Default concurrency is one.
- Assessment and CV worker counts are configurable.
- Tasks within a batch are independent.
- Failed tasks do not stop the batch.
- Abandoned running tasks become interrupted and retryable.

## Rationale

Model calls may run for a long time, and Streamlit request execution should remain responsive. The application is local and single-user, so Redis, Celery and cloud queues would add disproportionate complexity.

## Consequences

- SQLite task-state transitions must be explicit and tested.
- Concurrent workers require separate database sessions.
- The launcher must start both Streamlit and the worker.
