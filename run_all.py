"""Unified local development launcher for QueueForge Nexus.
Runs:
  1. Backend API (FastAPI / Uvicorn on http://127.0.0.1:8000)
  2. Background Worker (durable job consumer)
  3. Frontend Console & Reverse Proxy (on http://localhost:5173)
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
VENV_PYTHON = os.path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(VENV_PYTHON):
    VENV_PYTHON = sys.executable


def main():
    print("=" * 60)
    print("  QueueForge Nexus - Starting Local Services")
    print("=" * 60)
    print(f"Python: {VENV_PYTHON}")
    print(f"Directory: {ROOT_DIR}")

    processes: list[subprocess.Popen] = []

    def shutdown(signum=None, frame=None):
        print("\nStopping all services...")
        for p in processes:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(1)
        for p in processes:
            try:
                p.kill()
            except Exception:
                pass
        print("All services stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 1. Start Backend API
    print("\n[1/3] Starting FastAPI backend on http://127.0.0.1:8000 ...")
    api_proc = subprocess.Popen(
        [
            VENV_PYTHON,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        cwd=BACKEND_DIR,
    )
    processes.append(api_proc)

    # Give the API a brief moment to bind
    time.sleep(2)

    # 2. Start Worker
    print("[2/3] Starting Worker (worker-local-1) ...")
    worker_proc = subprocess.Popen(
        [
            VENV_PYTHON,
            "-m",
            "app.worker",
            "--worker-id",
            "worker-local-1",
            "--poll",
            "0.7",
        ],
        cwd=BACKEND_DIR,
    )
    processes.append(worker_proc)

    # 3. Start Frontend Console Dev Server
    print("[3/3] Starting Operations Console on http://localhost:5173 ...")
    frontend_proc = subprocess.Popen(
        [
            VENV_PYTHON,
            os.path.join(ROOT_DIR, "dev_server.py"),
        ],
        cwd=ROOT_DIR,
    )
    processes.append(frontend_proc)

    print("\n" + "=" * 60)
    print("  QueueForge Nexus is RUNNING!")
    print("=" * 60)
    print("  -> Console UI:   http://localhost:5173")
    print("  -> API Docs:     http://localhost:8000/docs")
    print("  -> Health Check: http://localhost:8000/api/health")
    print("=" * 60)
    print("Press Ctrl+C to stop all services.\n")

    try:
        while True:
            # Check if any child process crashed unexpectedly
            for p in processes:
                code = p.poll()
                if code is not None:
                    print(f"Warning: A service process (PID {p.pid}) exited with code {code}.")
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
