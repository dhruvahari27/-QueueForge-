"""Run a durable queue worker: python -m app.worker --worker-id worker-local-1"""
from __future__ import annotations

import argparse
import logging
import signal
import socket
import threading
import time


from .config import settings
from .database import SessionLocal
from .engine import run_once, ensure_worker, recover_expired_leases
from .models import Worker, utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("queueforge.worker")
stop_event = threading.Event()


def _handle_signal(signum, frame):
    log.info("Shutdown requested (signal=%s); finishing current task", signum)
    stop_event.set()


def heartbeat_thread(worker_id: str):
    interval = max(2, settings.lease_seconds // 3)
    while not stop_event.wait(interval):
        db = SessionLocal()
        try:
            worker = db.get(Worker, worker_id)
            if worker:
                worker.last_heartbeat = utcnow()
                if worker.current_job_id:
                    worker.status = "busy"
                elif worker.status not in {"paused", "draining"}:
                    worker.status = "idle"
                db.commit()
        except Exception:
            db.rollback()
            log.exception("Heartbeat failed")
        finally:
            db.close()


def serve(worker_id: str, poll_seconds: float) -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    db = SessionLocal()
    try:
        ensure_worker(db, worker_id)
        db.commit()
    finally:
        db.close()
    heart = threading.Thread(target=heartbeat_thread, args=(worker_id,), daemon=True, name=f"{worker_id}-heartbeat")
    heart.start()
    log.info("Worker %s started; polling every %.2fs; lease=%ss", worker_id, poll_seconds, settings.lease_seconds)
    while not stop_event.is_set():
        try:
            db = SessionLocal()
            try:
                recovered = recover_expired_leases(db)
                if recovered:
                    log.warning("Recovered %d expired job lease(s)", recovered)
            finally:
                db.close()
            worked = run_once(worker_id)
            if not worked:
                stop_event.wait(poll_seconds)
        except Exception:
            log.exception("Worker loop error; will retry")
            stop_event.wait(max(1.0, poll_seconds))
    db = SessionLocal()
    try:
        worker = db.get(Worker, worker_id)
        if worker:
            worker.status = "offline"
            worker.current_job_id = None
            worker.last_heartbeat = utcnow()
            db.commit()
    finally:
        db.close()
    stop_event.set()
    heart.join(timeout=2)
    log.info("Worker %s stopped", worker_id)


def main():
    parser = argparse.ArgumentParser(description="QueueForge Nexus worker")
    parser.add_argument("--worker-id", default=f"worker-{socket.gethostname()}-{int(time.time())}")
    parser.add_argument("--poll", type=float, default=0.7)
    args = parser.parse_args()
    serve(args.worker_id, max(0.1, min(30.0, args.poll)))


if __name__ == "__main__":
    main()
