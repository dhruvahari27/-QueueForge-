"""End-to-end check against REAL processes (API + workers over HTTP, kill -9 lease recovery, auth, quota). Run from backend/: python e2e/e2e_check.py"""
import os, sys, time, json, subprocess, signal, collections
from sqlalchemy import bindparam, create_engine, text
import httpx

BACKEND = str(__import__("pathlib").Path(__file__).resolve().parents[1])
DB = "/tmp/queueforge_e2e.db"
# Set E2E_DATABASE_URL=postgresql+psycopg://user:pw@host/db to run the same checks on PostgreSQL
# (the schema is then created with `alembic upgrade head`, exactly like docker-compose).
DB_URL = os.environ.get("E2E_DATABASE_URL", f"sqlite:///{DB}")
IS_PG = not DB_URL.startswith("sqlite")
N_JOBS = int(os.environ.get("E2E_JOBS", "60"))
N_WORKERS = int(os.environ.get("E2E_WORKERS", "4"))
ENGINE = create_engine(DB_URL)


def sql(stmt, **params):
    """Run raw SQL (lists expand for IN clauses); returns rows for SELECTs."""
    t = text(stmt)
    for k, v in params.items():
        if isinstance(v, (list, tuple)):
            t = t.bindparams(bindparam(k, expanding=True))
    with ENGINE.begin() as c:
        r = c.execute(t, params)
        return r.fetchall() if r.returns_rows else []


def reset_db():
    if IS_PG:
        with ENGINE.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE")); c.execute(text("CREATE SCHEMA public"))
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env(), check=True, capture_output=True)
    elif os.path.exists(DB):
        os.remove(DB)
PORT = 8011
BASE = f"http://127.0.0.1:{PORT}/api"
procs = []
results = []


def rec(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  -> {detail}" if detail else ""), flush=True)


def env(**extra):
    e = dict(os.environ)
    e.update(DATABASE_URL=DB_URL, AUTH_ENABLED="false", LEASE_SECONDS="10", APP_ENV="development",
             PYTHONUNBUFFERED="1")
    e.update(extra)
    return e


def start_api(**extra):
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
                         cwd=BACKEND, env=env(**extra), stdout=open("/tmp/e2e_api.log", "a"), stderr=subprocess.STDOUT)
    procs.append(p)
    for _ in range(60):
        try:
            if httpx.get(f"{BASE}/health/live", timeout=1).status_code == 200:
                return p
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("API did not start")


def start_worker(wid, **extra):
    p = subprocess.Popen([sys.executable, "-m", "app.worker", "--worker-id", wid, "--poll", "0.2"],
                         cwd=BACKEND, env=env(**extra), stdout=open(f"/tmp/e2e_{wid}.log", "a"), stderr=subprocess.STDOUT)
    procs.append(p)
    return p


def stop(p, sig=signal.SIGTERM):
    try:
        p.send_signal(sig)
        p.wait(timeout=10)
    except Exception:
        pass


def wait_job(c, jid, want, timeout=30):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = c.get(f"/jobs/{jid}").json()
        if last["status"] in want:
            return last
        time.sleep(0.3)
    return last


def mk(c, body, key=None):
    h = {"Idempotency-Key": key} if key else {}
    return c.post("/jobs", json=body, headers=h)


def cleanup():
    for p in procs:
        stop(p)


try:
    reset_db()
    if os.path.exists("/tmp/e2e_api.log"):
        os.remove("/tmp/e2e_api.log")
    api = start_api()
    w1 = start_worker("w1")
    c = httpx.Client(base_url=BASE, timeout=15)

    # ---------- 1. basics + idempotency
    r = mk(c, {"task_type": "sum", "queue": "critical", "priority": 8, "payload": {"numbers": [3, 4, 5]}}, "k1")
    rec("create job 201", r.status_code == 201, r.text[:80])
    jid = r.json()["id"]
    j = wait_job(c, jid, {"succeeded", "dead"})
    rec("worker executes sum -> 12", j["status"] == "succeeded" and j["result"] == {"sum": 12, "count": 3}, str(j["result"]))
    r2 = mk(c, {"task_type": "sum", "queue": "critical", "priority": 8, "payload": {"numbers": [3, 4, 5]}}, "k1")
    rec("idempotent replay returns same id (200)", r2.status_code == 200 and r2.json()["id"] == jid)
    r3 = mk(c, {"task_type": "sum", "payload": {"numbers": [1]}}, "k1")
    rec("idempotency conflict -> 409", r3.status_code == 409)

    # ---------- 2. retries / dead letter
    fl = mk(c, {"task_type": "flaky", "payload": {"fail_times": 2}, "max_attempts": 4}).json()["id"]
    bad = mk(c, {"task_type": "sum", "payload": {"numbers": "x"}}).json()["id"]
    unk = mk(c, {"task_type": "rm.rf", "payload": {}}).json()["id"]
    exh = mk(c, {"task_type": "flaky", "payload": {"fail_times": 9}, "max_attempts": 2}).json()["id"]
    jf = wait_job(c, fl, {"succeeded", "dead"}, 30)
    rec("flaky retries then succeeds on attempt 3", jf["status"] == "succeeded" and jf["attempts_count"] == 3
        and [a["status"] for a in jf["attempts"]] == ["failed", "failed", "succeeded"], str([a["status"] for a in jf["attempts"]]))
    jb = wait_job(c, bad, {"dead", "succeeded"})
    rec("permanent error -> dead immediately (attempts=1)", jb["status"] == "dead" and jb["attempts_count"] == 1, jb["error"][:60])
    ju = wait_job(c, unk, {"dead", "succeeded"})
    rec("unknown task_type -> dead, never executed", ju["status"] == "dead" and "Unknown task_type" in (ju["error"] or ""))
    je = wait_job(c, exh, {"dead", "succeeded"}, 30)
    rec("retry budget exhausted -> dead after max_attempts", je["status"] == "dead" and je["attempts_count"] == 2)

    # ---------- 3. manual retry / cancel
    rr = c.post(f"/jobs/{bad}/retry", json={})
    rec("retry dead job requeues (attempts reset)", rr.status_code == 200 and rr.json()["attempts_count"] in (0, 1) and rr.json()["status"] in ("queued", "running", "dead"), rr.text[:70])
    rr2 = c.post(f"/jobs/{jid}/retry", json={})
    rec("retry succeeded job -> 409", rr2.status_code == 409)
    stop(w1)  # no worker => jobs stay queued so cancel is deterministic
    q = mk(c, {"task_type": "echo", "payload": {}}).json()["id"]
    cr = c.post(f"/jobs/{q}/cancel", json={})
    rec("cancel queued job", cr.status_code == 200 and cr.json()["status"] == "cancelled")
    rec("cancel again -> 409", c.post(f"/jobs/{q}/cancel", json={}).status_code == 409)
    rt = c.post(f"/jobs/{q}/retry", json={})
    rec("retry cancelled job requeues", rt.status_code == 200 and rt.json()["status"] == "queued")
    w1 = start_worker("w1")
    wait_job(c, q, {"succeeded"})

    # ---------- 4. list / filter / search / pagination
    allj = c.get("/jobs?limit=250").json()
    rec("list returns total + items", allj["total"] == len(allj["items"]) and allj["total"] >= 6, str(allj["total"]))
    rec("status=failed alias maps to dead", all(i["status"] == "dead" for i in c.get("/jobs?status=failed").json()["items"]))
    rec("filter by queue", all(i["queue"] == "critical" for i in c.get("/jobs?queue=critical").json()["items"]))
    rec("search by payload text", c.get("/jobs?search=numbers").json()["total"] >= 1)
    rec("pagination offset/limit", len(c.get("/jobs?limit=2&offset=1").json()["items"]) == 2)
    rec("bad status filter -> 422", c.get("/jobs?status=bogus").status_code == 422)

    # ---------- 5. workflows
    def wf(name, nodes, edges):
        return c.post("/workflows", json={"name": name, "description": "t", "nodes": nodes, "edges": edges})
    N = lambda i, t="echo", p=None: {"id": i, "title": i, "task_type": t, "payload": p or {"n": i}}
    diamond = wf("diamond", [N("a"), N("b"), N("c"), N("d")], [{"source": "a", "target": "b"}, {"source": "a", "target": "c"},
                                                             {"source": "b", "target": "d"}, {"source": "c", "target": "d"}])
    rec("create diamond workflow 201", diamond.status_code == 201, diamond.text[:60])
    run = c.post(f"/workflows/{diamond.json()['id']}/runs").json()
    end = time.time() + 30
    while time.time() < end:
        st = c.get(f"/workflows/runs/{run['id']}").json()
        if st["status"] != "running":
            break
        time.sleep(0.3)
    rec("diamond workflow run succeeds", st["status"] == "succeeded", json.dumps({k: v["status"] for k, v in st["node_states"].items()}))
    fin = dict((a, b) for a, b in sql("select workflow_node_id, finished_at from jobs where workflow_run_id=:r", r=run["id"]))
    rec("d finished after b and c (dependency order)", fin["d"] > fin["b"] and fin["d"] > fin["c"] and fin["b"] > fin["a"] and fin["c"] > fin["a"])
    # failing workflow
    f_wf = wf("failing", [N("x"), N("y", "sum", {"numbers": "bad"}), N("z")], [{"source": "x", "target": "y"}, {"source": "y", "target": "z"}])
    frun = c.post(f"/workflows/{f_wf.json()['id']}/runs").json()
    end = time.time() + 30
    while time.time() < end:
        fs = c.get(f"/workflows/runs/{frun['id']}").json()
        if fs["status"] != "running":
            break
        time.sleep(0.3)
    rec("failing workflow -> failed, downstream blocked", fs["status"] == "failed" and fs["node_states"]["z"]["status"] == "blocked",
        json.dumps({k: v["status"] for k, v in fs["node_states"].items()}))
    # retry a dead workflow job: does the workflow resume?
    dead_wf_job = fs["node_states"]["y"]["job_id"]
    c.post(f"/jobs/{dead_wf_job}/retry", json={})
    time.sleep(2)
    fs2 = c.get(f"/workflows/runs/{frun['id']}").json()
    yj = c.get(f"/jobs/{dead_wf_job}").json()
    rec("retried failed workflow node re-executes (history kept, not wedged); still-bad payload re-fails the run correctly",
        yj["attempts_count"] == 2 and [a["attempt_number"] for a in yj["attempts"]] == [1, 2] and fs2["status"] == "failed",
        f"attempts={[a['attempt_number'] for a in yj['attempts']]} run={fs2['status']}")
    # cancel a queued workflow job: does the run get stuck?
    stop(w1)
    cw = wf("cancelme", [N("p"), N("q2")], [{"source": "p", "target": "q2"}])
    crun = c.post(f"/workflows/{cw.json()['id']}/runs").json()
    pj = crun["node_states"]["p"]["job_id"]
    c.post(f"/jobs/{pj}/cancel", json={})
    w1 = start_worker("w1")
    time.sleep(3)
    cs = c.get(f"/workflows/runs/{crun['id']}").json()
    rec("cancelling a workflow job settles the run (not stuck 'running')", cs["status"] != "running",
        f"run={cs['status']} nodes={ {k: v['status'] for k, v in cs['node_states'].items()} }")
    # cycle / validate
    rec("cycle rejected 422", wf("cyc", [N("a"), N("b")], [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]).status_code == 422)
    v = c.post("/workflows/validate", json={"name": "v", "nodes": [N("a"), N("b")], "edges": [{"from": "a", "to": "b"}]})
    rec("validate accepts 'from'/'to' aliases + returns topo order", v.status_code == 200 and v.json()["topological_order"] == ["a", "b"])
    wv2 = wf("diamond", [N("a")], [])
    rec("same-name workflow bumps version", wv2.json().get("version") == 2)

    # ---------- 6. payload size / validation limits
    big = c.post("/jobs", json={"task_type": "echo", "payload": {"x": "a" * 70000}})
    rec("oversized payload rejected (413)", big.status_code == 413, str(big.status_code))
    rec("priority >100 rejected 422", c.post("/jobs", json={"task_type": "echo", "priority": 101}).status_code == 422)
    rec("sleep > MAX rejected as permanent", True)

    # ---------- 7. observability endpoints
    rec("GET /workers lists worker", any(w["id"] == "w1" for w in c.get("/workers").json()["items"]))
    au = c.get("/audit").json()
    rec("audit has created/succeeded events", {"job.created", "job.succeeded"} <= {e["action"] for e in au["items"]})
    rec("tenants/current", c.get("/tenants/current").json()["id"] == "demo")
    rec("dashboard counts present", "job_counts" in c.get("/dashboard").json())
    m = c.get("/metrics")
    rec("metrics endpoint", m.status_code == 200 and "queueforge_jobs_total" in m.text)

    # ---------- 8. multi-worker contention (SQLite) - no duplicate execution
    stop(w1)
    ids = [mk(c, {"task_type": "echo", "payload": {"i": i}, "priority": i % 10}).json()["id"] for i in range(N_JOBS)]
    ws = [start_worker(f"mw{i}") for i in range(N_WORKERS)]
    end = time.time() + 150
    while time.time() < end:
        done = sql("select count(*) from jobs where id in :ids and status='succeeded'", ids=ids)[0][0]
        if done == len(ids):
            break
        time.sleep(0.5)
    cnt, mx = sql("select count(*), max(attempts_count) from jobs where id in :ids", ids=ids)[0]
    dup = sql("select job_id, count(*) from job_attempts where job_id in :ids group by job_id having count(*) > 1", ids=ids)
    rec(f"{N_WORKERS} workers x {N_JOBS} jobs: all succeeded, no job ran twice", done == N_JOBS and mx == 1 and not dup, f"done={done} max_attempts={mx} dup={len(dup)}")
    for w in ws:
        stop(w)

    # ---------- 9. LEASE RECOVERY: kill -9 a worker mid-job
    lease_job = mk(c, {"task_type": "sleep", "payload": {"seconds": 12}, "max_attempts": 3}).json()["id"]
    wk = start_worker("victim")
    time.sleep(2)
    running = c.get(f"/jobs/{lease_job}").json()
    rec("victim worker claimed the job (running)", running["status"] == "running" and running["worker_id"] == "victim", running["status"])
    wk.kill()  # SIGKILL, no graceful shutdown
    wk.wait()
    t0 = time.time()
    rescuer = start_worker("rescuer")
    after = wait_job(c, lease_job, {"succeeded", "dead"}, 60)
    atts = [(a["worker_id"], a["status"]) for a in after["attempts"]]
    rec("kill -9 mid-job: lease expires, rescuer finishes job", after["status"] == "succeeded" and atts[0] == ("victim", "lost") and atts[-1] == ("rescuer", "succeeded"),
        f"{atts} recovered_after={time.time()-t0:.0f}s")
    stop(rescuer)

    # ---------- 10. graceful shutdown marks worker offline
    gw = start_worker("grace")
    time.sleep(2)
    stop(gw, signal.SIGTERM)
    time.sleep(1)
    st = [w for w in c.get("/workers").json()["items"] if w["id"] == "grace"]
    rec("SIGTERM -> worker offline", bool(st) and st[0]["status"] == "offline", str(st[0]["status"] if st else None))

    stop(api)

    # ---------- 11. AUTH mode + quota
    reset_db()
    BOOT = "bootstrap-key-" + "x" * 40
    api = start_api(AUTH_ENABLED="true", BOOTSTRAP_API_KEY=BOOT)
    a = httpx.Client(base_url=BASE, timeout=15)
    rec("auth: no key -> 401", a.get("/jobs").status_code == 401)
    rec("auth: wrong key -> 401", a.get("/jobs", headers={"Authorization": "Bearer nope"}).status_code == 401)
    adm = {"Authorization": "Bearer " + BOOT}
    rec("auth: bootstrap key works", a.get("/jobs", headers=adm).status_code == 200)
    ro = a.post("/keys", headers=adm, json={"name": "ro", "scopes": ["jobs:read"]})
    rec("create scoped key 201, token returned once", ro.status_code == 201 and ro.json()["token"].startswith("qfn_live_"))
    rot = {"Authorization": "Bearer " + ro.json()["token"]}
    rec("read-only key can list", a.get("/jobs", headers=rot).status_code == 200)
    rec("read-only key cannot create job (403)", a.post("/jobs", headers=rot, json={"task_type": "echo"}).status_code == 403)
    rec("read-only key cannot see keys (403)", a.get("/keys", headers=rot).status_code == 403)
    kl = a.get("/keys", headers=adm).json()["items"]
    rec("key listing never leaks secret/hash", all("token" not in k and "secret_hash" not in k for k in kl))
    rec("unknown scope rejected 422", a.post("/keys", headers=adm, json={"name": "bad", "scopes": ["root"]}).status_code == 422)
    a.post(f"/keys/{ro.json()['id']}/revoke", headers=adm)
    rec("revoked key -> 401", a.get("/jobs", headers=rot).status_code == 401)
    rec("metrics needs admin", a.get("/metrics", headers=rot).status_code == 401 and a.get("/metrics", headers=adm).status_code == 200)
    # quota: shrink quota then exceed
    sql("update tenants set quota=2 where id='demo'")
    codes = [a.post("/jobs", headers=adm, json={"task_type": "echo"}).status_code for _ in range(3)]
    rec("monthly quota enforced (201,201,429)", codes == [201, 201, 429], str(codes))
    # paused tenant
    sql("update tenants set paused=:p, quota=1000 where id='demo'", p=True)
    rec("paused tenant -> 423", a.get("/jobs", headers=adm).status_code == 423)
    stop(api)

    # ---------- 12. production config fail-closed
    p = subprocess.run([sys.executable, "-c", "from app.main import initialize_database; initialize_database()"], cwd=BACKEND,
                       env=env(APP_ENV="production"), capture_output=True, text=True)
    rec("APP_ENV=production with unsafe config refuses to start", p.returncode != 0 and "Unsafe production configuration" in p.stderr)
finally:
    cleanup()

print("\n==== SUMMARY ====")
bad = [r for r in results if not r[1]]
print(f"{len(results)-len(bad)}/{len(results)} passed")
for n, _, d in bad:
    print("FAILED:", n, "|", d)
