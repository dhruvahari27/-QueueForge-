#!/bin/sh
set -e

# Run database migrations if PostgreSQL or a migration URL is provided
if [ -n "$DATABASE_URL" ]; then
  echo "[QueueForge] Applying database schema migrations..."
  alembic upgrade head || echo "[QueueForge] Migration completed or skipped."
fi

if [ "$MODE" = "worker" ]; then
  echo "[QueueForge] Starting dedicated worker process..."
  exec python -m app.worker --worker-id "${WORKER_ID:-worker-railway-1}" --poll "${POLL_INTERVAL:-0.7}"
elif [ "$MODE" = "api" ]; then
  echo "[QueueForge] Starting FastAPI control plane on port ${PORT:-8000}..."
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
else
  # Default: all-in-one mode (runs worker in background + API in foreground)
  echo "[QueueForge] Starting all-in-one stack (API + Worker) on port ${PORT:-8000}..."
  python -m app.worker --worker-id "${WORKER_ID:-worker-railway-1}" --poll "${POLL_INTERVAL:-0.7}" &
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
fi
