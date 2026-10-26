# 🚀 Deploying QueueForge Nexus to Render

Render is an excellent cloud platform that offers a generous **Free Tier** for both PostgreSQL databases and Web Services.

With QueueForge's pre-configured `render.yaml` blueprint, you can deploy the entire stack (Database + API + Workers + Console UI) in **one click**.

---

## ⚡ Method 1: One-Click Blueprint Deployment (Recommended)

1. Log into your account on [render.com](https://render.com).
2. In the top navigation bar, click **"New +"** &rarr; select **"Blueprint"**.
3. Connect your GitHub repository: **`dhruvahari27/-QueueForge-`**.
4. Render will read [`render.yaml`](../render.yaml) and show you the resources it will create:
   - **`queueforge-db`** (Managed PostgreSQL instance on Free tier)
   - **`queueforge-nexus`** (Docker Web Service running API + Background Worker + Operations Console)
5. Click **"Apply"**.
6. Render will automatically provision PostgreSQL, run database migrations, launch the worker fleet, and expose your public HTTPS domain!

---

## 🛠️ Method 2: Manual Dashboard Setup

If you prefer setting up the services manually via the Render dashboard:

### Step 1: Create PostgreSQL Database
1. Click **"New +"** &rarr; select **"PostgreSQL"**.
2. Name: `queueforge-db`
3. Database: `queueforge`
4. User: `queueforge`
5. Plan: **Free**
6. Click **"Create Database"**.
7. Once created, copy the **Internal Database URL** (e.g. `postgres://queueforge:xxx@dpg-xxx:5432/queueforge`).

---

### Step 2: Create Web Service
1. Click **"New +"** &rarr; select **"Web Service"**.
2. Connect your repository: **`dhruvahari27/-QueueForge-`**.
3. Settings:
   - **Name**: `queueforge-nexus`
   - **Language / Runtime**: **Docker**
   - **Dockerfile Path**: `Dockerfile`
   - **Instance Type**: **Free**
4. In the **Environment Variables** section, add:
   - `DATABASE_URL` = *(Paste the Internal Database URL from Step 1)*
   - `APP_ENV` = `development`
   - `MODE` = `all`
5. In **Health Check Path**, enter: `/api/health`
6. Click **"Create Web Service"**.

---

## 🌐 Accessing Your Deployment

Once Render finishes deploying (usually 1-2 minutes):
- **Live Operations Console**: `https://queueforge-nexus.onrender.com/`
- **Interactive OpenAPI Docs**: `https://queueforge-nexus.onrender.com/docs`
- **Health Check**: `https://queueforge-nexus.onrender.com/api/health`
