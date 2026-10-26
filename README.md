# <div align="center">⚡ QueueForge Nexus</div>

<div align="center">

**Enterprise-Grade Durable Background Jobs & Dependency-Aware DAG Workflows**

[![Python Version](https://img.shields.io/badge/Python-3.12%20%7C%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple?style=for-the-badge)](LICENSE)

*A full-stack asynchronous orchestration engine with a FastAPI control plane, lease-fenced distributed workers, and an Aurora glassmorphism operations console.*

[✨ Features](#-core-capabilities) • [🏗️ Architecture](#️-system-architecture) • [🚀 Quick Start](#-quick-start) • [📡 REST API](#-rest-api) • [🧪 Testing](#-testing--quality) • [📖 Documentation](#-documentation--adrs)

</div>

---

## 🌟 Overview

**QueueForge Nexus** is an open-source, production-minded orchestration platform engineered for mission-critical background tasks and complex multi-step Directed Acyclic Graph (DAG) pipelines. 

Unlike simple message queues, QueueForge provides **at-least-once execution guarantees**, distributed attempt fencing, heartbeat lease recovery, tenant quota policing, and a live web console with zero npm dependencies.

```text
┌───────────────────────────────────────────────────────────────────────────┐
│                     QueueForge Operations Console                         │
│             http://localhost:5173  (Aurora Glassmorphic UI)               │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │ HTTP / REST
                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                    FastAPI Control Plane (:8000)                          │
│     • Validation & RBAC (PBKDF2)          • DAG Topology Engine           │
│     • Idempotency Deduplication           • Prometheus Metrics & Audit    │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │ SQLAlchemy 2.0
                                      ▼
                      ┌───────────────────────────────┐
                      │   PostgreSQL 16 (or SQLite)   │
                      │   FOR UPDATE SKIP LOCKED      │
                      └───────────────┬───────────────┘
                                      │ Distributed Leases
                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                     Autonomous Worker Fleet                               │
│     • Prioritized Queue Claims            • Lease Heartbeats & Renewal    │
│     • Attempt Fencing & Retries           • Dead-Letter Isolation        │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Core Capabilities

| Capability | Engineering Guarantee |
|---|---|
| **Durable Jobs** | Fully persisted job states (`queued` → `running` → `succeeded` / `dead` / `cancelled`). |
| **Worker Lease Engine** | Periodic heartbeat lease renewal. Expired leases are safely reclaimed by surviving workers. |
| **Fencing Tokens** | Execution attempts are strictly versioned (`attempt_number`), guaranteeing stale workers cannot overwrite fresh results. |
| **DAG Workflows** | Directed Acyclic Graph engine with automated cycle detection; unlocks dependent child tasks upon upstream success. |
| **Idempotency** | Client-supplied `Idempotency-Key` prevents duplicated job creation under network retries. |
| **Multi-Tenancy & Auth** | Salted PBKDF2 hashed tokens with granular scopes (`jobs:read`, `jobs:write`, `workflows:run`, `admin`). |
| **Operations Console** | Sleek glassmorphism UI with live state polling, real-time metrics, node graph inspector, and readable typography. |

---

## 🚀 Quick Start

### Option 1: One-Click Local Launcher (Windows / Linux / macOS)

QueueForge Nexus comes with a zero-setup unified development runner that launches the **Backend API**, **Worker Engine**, and **Frontend Console** together:

#### Windows (PowerShell / Batch)
```powershell
# Double-click run_project.bat OR run from PowerShell:
.\run_project.ps1
```

#### Manual Python Execution
```bash
# 1. Enter the backend directory and set up Python 3.12
cd backend
uv venv --python 3.12 .venv
# Windows: .venv\Scripts\activate | Unix: source .venv/bin/activate
pip install -r requirements-dev.txt

# 2. Launch the unified stack
cd ..
python run_all.py
```

Open in your browser:
- **Operations Console**: [http://localhost:5173](http://localhost:5173)
- **Interactive Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/api/health](http://localhost:8000/api/health)

---

### Option 2: Docker Compose

For a complete containerized stack with **PostgreSQL 16**, **Redis**, **API**, **Worker**, and **Nginx**:

```bash
# 1. Clone & copy environment settings
cp .env.example .env

# 2. Build and launch services
docker compose up --build
```

Stop the stack at any time with `docker compose down`.

---

## 📡 REST API Reference

The FastAPI Control Plane provides a RESTful interface documented with OpenAPI v3:

| Method | Endpoint | Description |
|:---:|---|---|
| `GET` | `/api/health` | Comprehensive database and service readiness probe |
| `GET` | `/api/dashboard` | Aggregated tenant metrics, throughput, and status counts |
| `POST` | `/api/jobs` | Enqueue a durable job (supports `Idempotency-Key`) |
| `GET` | `/api/jobs` | Paginated and filtered job listing with search |
| `GET` | `/api/jobs/{id}` | Inspect job state, attempts history, and logs |
| `POST` | `/api/jobs/{id}/retry` | Re-queue terminal dead-letter or cancelled jobs |
| `POST` | `/api/jobs/{id}/cancel` | Cancel an unassigned queued job |
| `GET` | `/api/workers` | Active worker heartbeats, current leases, and status |
| `POST` | `/api/workflows` | Define a versioned DAG dependency graph |
| `POST` | `/api/workflows/validate`| Validate nodes and cycle detection for DAGs |
| `POST` | `/api/workflows/{id}/runs` | Trigger durable execution of a DAG workflow run |
| `GET` | `/api/keys` | List tenant-scoped API keys (PBKDF2 secured) |
| `POST` | `/api/keys` | Generate a new bearer key with granular scopes |

#### Sample: Enqueue a Task via cURL

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: task-uid-94812" \
  -d '{
    "task_type": "sum",
    "queue": "critical",
    "priority": 9,
    "payload": {"numbers": [10, 25, 65]},
    "max_attempts": 3
  }'
```

---

## 🧪 Testing & Quality

QueueForge Nexus maintains high test coverage with unit, regression, concurrency, and security scans:

```bash
cd backend

# Run full test suite with coverage
pytest -q --cov=app --cov-report=term-missing

# Critical lint checks
ruff check app tests scripts --select E9,F63,F7,F82

# Security static analysis
bandit -q -r app scripts
```

The test harness verifies idempotency deduplication, stale attempt fencing, lease recovery under simulated worker crashes, cross-tenant isolation, and DAG execution order.

---

## 📂 Project Structure

```text
queueforge-nexus/
├── backend/
│   ├── app/
│   │   ├── config.py         # Dynamic environment settings & production validators
│   │   ├── database.py       # SQLAlchemy 2.0 engine & session maker
│   │   ├── engine.py         # Core worker execution & heartbeat leasing logic
│   │   ├── main.py           # FastAPI control plane routes & middleware
│   │   ├── models.py         # Declarative ORM schemas (Job, Worker, Tenant, Workflow)
│   │   ├── observability.py  # Prometheus metric counters & histograms
│   │   ├── security.py       # PBKDF2 hashing, bearer tokens & RBAC scopes
│   │   └── workflows.py      # DAG graph validation & dependent job release
│   ├── migrations/           # Alembic database migrations
│   ├── tests/                # Test suite (unit, regression, security, workers)
│   └── scripts/              # Load testing & API key generators
├── frontend/
│   ├── index.html            # Operations console UI (vanilla glassmorphism)
│   ├── theme.css             # Fluid responsive layout & readable typography
│   ├── live-bridge.js        # Reactive bridge connecting UI to FastAPI backend
│   └── nginx.conf            # Production reverse proxy configuration
├── docs/                     # Architectural diagrams, ADRs & security threat models
├── run_all.py                # Unified cross-platform local development runner
├── dev_server.py             # Frontend dev server with integrated /api proxy
├── docker-compose.yml        # Multi-container orchestration definition
└── Makefile                  # Developer workflow targets
```

---

## 📖 Documentation & ADRs

- 📐 [**System Architecture**](docs/ARCHITECTURE.md) - Deep dive into consistency models and recovery workflows.
- 🛡️ [**Threat Model**](docs/THREAT_MODEL.md) - Security boundaries, RBAC matrix, and defense-in-depth principles.
- 📋 [**Runbook**](docs/RUNBOOK.md) - Operational playbooks for lease expiration, dead-letter recovery, and incident triage.
- 📝 [**Architecture Decision Records (ADRs)**](docs/adr/) - Historical context for Postgres locking, at-least-once delivery, and tenant keys.

---

## 📜 License

Distributed under the **MIT License**. See `LICENSE` for more information.
