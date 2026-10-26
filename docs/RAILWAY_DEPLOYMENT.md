# 🚂 Deploying QueueForge Nexus to Railway

This guide walks you through deploying **QueueForge Nexus** with PostgreSQL, the FastAPI control plane, background workers, and the web console on [Railway](https://railway.app).

---

## ⚡ Quick 3-Step Deployment

### Step 1: Create a Railway Project from GitHub

1. Go to [railway.app](https://railway.app) and sign in with GitHub.
2. Click **"+ New Project"** &rarr; Select **"Deploy from GitHub repo"**.
3. Choose your repository: **`dhruvahari27/-QueueForge-`**.
4. Railway will automatically detect the root `Dockerfile` and `railway.json`.

---

### Step 2: Add PostgreSQL Database

1. In your Railway project canvas, click **"+ New"** (or press `Ctrl + K`).
2. Select **"Database"** &rarr; choose **"Add PostgreSQL"**.
3. Railway will provision a managed PostgreSQL 16 instance.
4. Click on your **QueueForge** service card &rarr; go to the **Variables** tab:
   - Click **"Add Variable Reference"** &rarr; select **`DATABASE_URL`** from your PostgreSQL service (`${{Postgres.DATABASE_URL}}`).
   - *(Note: QueueForge automatically converts `postgresql://` to `postgresql+psycopg://` under the hood).*

---

### Step 3: Configure Variables & Expose Domain

In your **QueueForge** service **Variables** tab, set:

| Variable | Value | Description |
|---|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Connects to Railway PostgreSQL |
| `APP_ENV` | `development` | Allows immediate local/demo evaluation without API keys |
| `MODE` | `all` *(Default)* | Runs both FastAPI API + Background Worker in one container |

#### Generate a Public URL:
1. In the QueueForge service, go to **Settings** &rarr; **Networking**.
2. Click **"Generate Domain"** (e.g. `queueforge-production.up.railway.app`).
3. Click the generated URL to open the **QueueForge Nexus Operations Console**!

---

## 🏗️ Architecture on Railway

By default, the root `Dockerfile` runs in **all-in-one mode (`MODE=all`)**:
- Automatically applies pending Alembic database migrations on startup.
- Launches the durable background worker in the background.
- Serves the FastAPI REST API and Swagger Docs (`/docs`).
- Serves the Aurora Glassmorphism Operations Console at the root URL (`/`).

### Optional: Separate Web & Worker Services
If you prefer scaling workers independently from the API on Railway:
1. **Web Service**: Deploy from GitHub, set variable `MODE=api`.
2. **Worker Service**: Add a second service from the same repo, set variable `MODE=worker`.
