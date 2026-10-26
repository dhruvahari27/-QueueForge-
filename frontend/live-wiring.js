/*
 * QueueForge Nexus · live wiring.
 * When the console is connected to a real API (Settings → Live backend connection), every control below
 * performs the matching API call instead of mutating illustrative browser state:
 *   retry · real attempt history · workflow runs · workers · audit log · API keys · tenant · dashboard tiles.
 * When not connected, nothing here is active and the demo behaviour is unchanged.
 * Click interception happens on `window` (capture) so it runs before the demo handlers.
 */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const live = () => Boolean(window.__qfnLive && window.__qfnLive.connected && window.__qfnLiveApi);
  const api = (path, opts) => window.__qfnLiveApi.request(path, opts);
  const say = (m) => (window.toast ? window.toast(m) : undefined);
  const enc = encodeURIComponent;
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const items = (r) => (Array.isArray(r.data) ? r.data : (r.data && r.data.items) || []);
  const reason = (e) => (e && e.status === 403 ? 'this API key lacks the required scope' : (e && e.message) || String(e));
  function toMs(v) {
    if (!v) return null;
    let s = String(v);
    if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(s) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(s)) s += 'Z';
    const n = Date.parse(s); return Number.isFinite(n) ? n : null;
  }
  const currentView = () => ($('crumb-view') ? $('crumb-view').textContent : '');

  /* ---------------- dashboard tiles ---------------- */
  function liveTiles() {
    if (!live()) return;
    const d = window.__qfnLive.dashboard; const list = (typeof jobs !== 'undefined') ? jobs : [];
    const counts = (d && d.job_counts) || {};
    const total = d ? d.total_jobs : list.length;
    const set = (el, v) => { if (el) el.textContent = v; };
    set($('metric-processed'), Number(total).toLocaleString());
    const ok = counts.succeeded || 0, bad = counts.dead || 0;
    const tiles = document.querySelectorAll('#view-overview .metrics .metric');
    if (tiles[1]) set(tiles[1].querySelector('.metric-value'), ok + bad ? (ok / (ok + bad) * 100).toFixed(1) + '%' : '—');
    const dur = list.filter((j) => j.started_at && j.finished_at && j.status === 'succeeded').map((j) => j.finished_at - j.started_at).sort((a, b) => a - b);
    if (tiles[2]) set(tiles[2].querySelector('.metric-value'), dur.length ? Math.round(dur[Math.min(dur.length - 1, Math.floor(dur.length * 0.95))]) + ' ms' : '—');
    if (d && d.active_workers != null) set($('active-workers'), d.active_workers + ' / ' + (d.workers || []).length);
    else set($('active-workers'), '—');
    set($('obs-failed'), String(bad));
    tiles.forEach((t) => {
      const tr = t.querySelector('.trend'); if (tr) { tr.textContent = '● live'; tr.classList.remove('down'); }
      const note = t.querySelector('.metric-note'); if (note) note.textContent = 'from API';
    });
    const eyebrow = document.querySelector('.page-heading .eyebrow .muted');
    if (eyebrow && currentView() === 'Overview') eyebrow.textContent = 'LIVE DATA';
  }

  /* ---------------- retry, real attempt history ---------------- */
  function installJobOverrides() {
  const prevRetry = window.retryJob;
  window.retryJob = async function (id) {
    if (!live()) return prevRetry ? prevRetry(id) : undefined;
    try {
      await api('/jobs/' + enc(id) + '/retry', { method: 'POST', body: JSON.stringify({ reason: 'console_retry' }) });
      await window.__qfnLiveApi.sync(true);
      say('Job requeued on the backend');
      if (typeof selectedId !== 'undefined' && selectedId === id) window.openJob(id);
    } catch (e) { say('Could not retry job: ' + reason(e)); }
  };

  const prevOpen = window.openJob;
  window.openJob = function (id) {
    prevOpen(id);
    if (live()) loadRealAttempts(id);
  };
  }
  async function loadRealAttempts(id) {
    try {
      const r = await api('/jobs/' + enc(id));
      if (typeof selectedId !== 'undefined' && selectedId !== id) return;
      const sec = [...document.querySelectorAll('#drawer-content .drawer-section')].find((s) => /Attempt history/i.test(s.textContent));
      if (!sec) return;
      const rows = (r.data.attempts || []).map((a) => {
        const s = toMs(a.started_at), f = toMs(a.finished_at);
        const dur = s && f ? ' · ' + (f - s) + ' ms' : '';
        const good = a.status === 'succeeded';
        const badge = a.status === 'lost' ? '<span class="status danger">× lost</span>' : window.stat(a.status === 'failed' ? 'failed' : a.status);
        return '<div class="attempt-row"><div class="attempt-bullet ' + (good ? 'ok' : '') + '">' + (good ? '✓' : a.status === 'running' ? '◌' : '×') + '</div><div class="attempt-content"><b>Attempt ' + a.attempt_number + '</b><span>' + esc(a.worker_id) + ' · ' + window.ago(s) + dur + '</span>' +
          (a.error ? '<small>' + esc(a.error) + '</small>' : '') + (a.result ? '<span>' + esc(JSON.stringify(a.result)) + '</span>' : '') + '</div>' + badge + '</div>';
      }).join('') || '<div style="color:var(--muted);font-size:10px;padding:10px 0">No worker attempts recorded yet.</div>';
      sec.innerHTML = '<h3>Attempt history <span class="status success" style="margin-left:6px">live</span></h3>' + rows;
    } catch (_) { /* keep the summary view */ }
  }

  /* ---------------- workflows: run on the backend ---------------- */
  function chainGraph(w) {
    const n = Math.max(1, w.tasks || 3);
    const nodes = Array.from({ length: n }, (_, i) => ({ id: 'step_' + (i + 1), title: 'Step ' + (i + 1), type: 'task' }));
    return { nodes, edges: nodes.slice(1).map((x, i) => ({ from: nodes[i].id, to: x.id })) };
  }
  async function runLiveWorkflow(w) {
    if (!w.graph) w.graph = chainGraph(w);
    const nodes = w.graph.nodes.map((n) => ({ id: n.id, title: n.title, task_type: 'echo', queue: 'workflows', payload: { step: n.title, kind: n.type } }));
    const edges = w.graph.edges.map((e) => ({ source: e.from, target: e.to }));
    const sig = JSON.stringify([w.name, nodes, edges]);
    try {
      if (!w.__live || w.__live.sig !== sig) {
        const created = await api('/workflows', { method: 'POST', body: JSON.stringify({ name: w.name, description: w.desc || '', nodes, edges }) });
        w.__live = { id: created.data.id, sig };
      }
      const run = (await api('/workflows/' + enc(w.__live.id) + '/runs', { method: 'POST' })).data;
      say('Workflow run started on the backend · ' + run.id);
      await window.__qfnLiveApi.sync(true);
      pollRun(run.id, w.name);
    } catch (e) { say('Could not run workflow: ' + reason(e)); }
  }
  function pollRun(runId, name) {
    let n = 0;
    const t = setInterval(async () => {
      n += 1;
      try {
        const st = (await api('/workflows/runs/' + enc(runId))).data;
        await window.__qfnLiveApi.sync(true);
        if (st.status !== 'running' || n > 120) {
          clearInterval(t);
          const done = Object.values(st.node_states || {}).filter((x) => x.status === 'succeeded').length;
          say('Workflow "' + name + '" ' + st.status + ' · ' + done + '/' + Object.keys(st.node_states || {}).length + ' steps succeeded');
        }
      } catch (_) { clearInterval(t); }
    }, 1000);
  }
  function selectedWorkflow(idx) {
    if (typeof wf === 'undefined') return null;
    if (Number.isInteger(idx) && wf[idx]) return wf[idx];
    const cards = [...document.querySelectorAll('#studio-library .workflow-card')];
    const i = cards.findIndex((c) => c.querySelector('.status.running'));
    return wf[i >= 0 ? i : 0];
  }

  /* ---------------- workers / audit / keys / tenant ---------------- */
  async function renderLiveWorkers() {
    const grid = $('workers-grid'); if (!grid) return;
    ['pause-button', 'nexus-worker-create'].forEach((id) => { if ($(id)) $(id).style.display = 'none'; });
    try {
      const list = items(await api('/workers'));
      const fresh = list.filter((w) => w.status === 'idle' || w.status === 'busy');
      if ($('worker-count')) $('worker-count').textContent = fresh.length + ' active';
      grid.innerHTML = list.length ? list.map((w) => {
        const st = w.status === 'busy' ? 'running' : (w.status === 'idle' ? 'idle' : 'stale');
        return '<section class="panel worker-card"><div class="worker-top"><div class="worker-mark ' + (st === 'running' || st === 'idle' ? 'active' : '') + '">⌘</div>' + window.stat(st) + '</div><h3>' + esc(w.id) + '</h3><p>' + esc(w.hostname) + ' · ' + (w.current_job_id ? 'running ' + esc(w.current_job_id) : 'waiting for work') + '</p>' +
          '<div class="worker-meters"><div><span>CONCURRENCY</span><b>' + esc(w.concurrency) + '</b></div><div><span>STATUS</span><b>' + esc(w.status) + '</b></div></div><div class="worker-foot"><span>' + esc((w.metadata || {}).engine || 'worker') + '</span><span>Heartbeat ' + window.ago(toMs(w.last_heartbeat)) + '</span></div></section>';
      }).join('') : '<div class="nx-empty">No worker has registered yet. Start one with <code>python -m app.worker</code>.</div>';
    } catch (e) { grid.innerHTML = '<div class="nx-empty">Could not load workers: ' + esc(reason(e)) + '</div>'; }
  }

  let auditCache = null, auditWriting = false, auditObserver = null;
  async function renderLiveAudit(refetch) {
    const list = $('nx-audit-list'); if (!list) return;
    try {
      if (refetch !== false || !auditCache) auditCache = items(await api('/audit?limit=200'));
    } catch (e) { auditWriting = true; list.innerHTML = '<div class="nx-empty">Could not load audit events: ' + esc(reason(e)) + '</div>'; auditWriting = false; if (auditObserver) auditObserver.takeRecords(); return; }
    const kind = $('nx-audit-filter') ? $('nx-audit-filter').value : 'all';
    const q = ($('nx-audit-search') ? $('nx-audit-search').value : '').toLowerCase();
    const shown = auditCache.filter((e) => (kind === 'all' || e.kind === kind) && (e.action + ' ' + e.detail + ' ' + e.actor + ' ' + e.id).toLowerCase().includes(q));
    auditWriting = true;
    list.innerHTML = shown.length ? shown.map((e) => '<div class="nx-audit-row"><div class="nx-audit-symbol">' + (e.kind === 'warn' ? '!' : e.kind === 'ok' ? '✓' : '⌁') + '</div><div class="nx-audit-copy"><b>' + esc(e.action) + '</b><span>' + esc(e.detail) + ' · ' + esc(e.actor) + ' · ' + esc(e.id) + '</span></div><time class="nx-audit-time">' + new Date(toMs(e.created_at)).toLocaleString() + '</time></div>').join('') : '<div class="nx-empty">No events match this view.</div>';
    auditWriting = false;
    if (auditObserver) auditObserver.takeRecords();
    const set = (id, v) => { if ($(id)) $(id).textContent = v; };
    set('nx-audit-count', auditCache.length); set('nx-audit-warn', auditCache.filter((e) => e.kind === 'warn').length); set('nx-audit-ok', auditCache.filter((e) => e.kind === 'ok').length);
    document.querySelectorAll('#nx-view-audit .nx-kpi').forEach((k) => { if (/Audit backend/i.test(k.textContent)) { k.querySelector('b').textContent = 'Live API'; k.querySelector('small').textContent = 'audit_events table'; } });
  }

  let keyBusy = false;
  async function renderLiveKeys() {
    const body = $('nx-key-table'); if (!body) return;
    const view = $('nx-view-security');
    const badge = view && view.querySelector('.nx-toolbar .status'); if (badge) badge.textContent = 'LIVE';
    const note = view && view.querySelector('.nx-notice'); if (note) note.innerHTML = '<strong>Live API keys.</strong> These records come from the backend. Raw tokens are shown once at creation; only a salted hash is stored. Creating or revoking a key requires the <code>keys:manage</code> scope.';
    try {
      const list = items(await api('/keys'));
      body.innerHTML = list.map((k) => '<tr><td><strong>' + esc(k.name) + '</strong><div style="font:8px ui-monospace,monospace;color:var(--muted);margin-top:5px">' + esc(k.id) + '</div></td><td><span class="nx-key">' + esc(k.prefix) + '…</span></td><td>' + (k.scopes || []).map((s) => '<span class="nx-scope">' + esc(s) + '</span>').join('') + '</td><td>' + window.stat(k.revoked ? 'revoked' : 'healthy') + '</td><td><div class="nx-actions">' + (k.revoked ? '<span class="status muted">Revoked</span>' : '<button class="btn btn-secondary btn-small" data-nx="key-revoke" data-id="' + esc(k.id) + '">Revoke</button>') + '</div></td></tr>').join('') || '<tr><td colspan="5"><div class="nx-empty">No API keys.</div></td></tr>';
      if ($('nx-key-count')) $('nx-key-count').textContent = list.length;
      if ($('nx-key-active')) $('nx-key-active').textContent = list.filter((k) => !k.revoked).length;
    } catch (e) { body.innerHTML = '<tr><td colspan="5"><div class="nx-empty">Could not load keys: ' + esc(reason(e)) + '</div></td></tr>'; }
  }
  const SCOPE_MAP = { 'jobs:read': ['jobs:read'], 'jobs:write': ['jobs:read', 'jobs:write'], 'workflows:write': ['workflows:read', 'workflows:write'], 'workers:read': ['workers:read'], admin: ['admin'] };
  async function createLiveKey() {
    if (keyBusy) return; const name = $('nx-key-name').value.trim();
    if (!name) { say('Enter a name for this key'); return; }
    keyBusy = true;
    try {
      const made = (await api('/keys', { method: 'POST', body: JSON.stringify({ name, scopes: SCOPE_MAP[$('nx-key-scope').value] || ['jobs:read'] }) })).data;
      $('nx-key-name').value = '';
      showToken(made.token, made.name);
      renderLiveKeys();
    } catch (e) { say('Could not create key: ' + reason(e)); } finally { keyBusy = false; }
  }
  function showToken(token, name) {
    const old = $('qfn-token-modal'); if (old) old.remove();
    const m = document.createElement('div'); m.id = 'qfn-token-modal'; m.className = 'modal-backdrop';
    m.innerHTML = '<div class="modal" role="dialog" aria-modal="true"><div class="modal-head"><div><div class="modal-kicker">API KEY CREATED</div><h2>Copy “' + esc(name) + '” now</h2><p>This token is shown once. The server stores only a salted hash.</p></div></div><div class="modal-body"><div class="nx-key" style="user-select:all">' + esc(token) + '</div></div><div class="modal-footer"><button class="btn btn-secondary" id="qfn-token-copy">Copy token</button><button class="btn btn-primary" id="qfn-token-close">Done</button></div></div>';
    document.body.appendChild(m);
    $('qfn-token-copy').onclick = () => window.copyText(token, 'Token copied');
    $('qfn-token-close').onclick = () => m.remove();
  }
  async function renderLiveTenant() {
    const v = $('view-tenants'); if (!v) return;
    try {
      const t = (await api('/tenants/current')).data; const d = window.__qfnLive.dashboard;
      const initials = (t.name || '?').split(/\s+/).map((s) => s[0] || '').join('').slice(0, 2).toUpperCase();
      v.innerHTML = '<div class="feature-banner"><div class="feature-icon">▦</div><div class="feature-copy"><b>Tenant · live from the API</b><p>The tenant is derived from your API key on the server. Creating, pausing or resizing tenants is not exposed by the API in this version.</p></div></div>' +
        '<section class="panel"><div class="panel-head"><div><h2>Current tenant</h2><p>GET /api/tenants/current</p></div>' + window.stat(t.paused ? 'paused' : 'healthy') + '</div><div class="tenant-row"><div class="tenant-avatar">' + esc(initials) + '</div><div class="tenant-copy"><b>' + esc(t.name) + '</b><span>tenant_id: ' + esc(t.id) + ' · created ' + esc(new Date(toMs(t.created_at)).toLocaleDateString()) + '</span></div><span class="tenant-plan">' + esc(String(t.plan).toUpperCase()) + '</span><b class="tenant-usage">' + (d ? d.total_jobs : '—') + ' jobs · quota ' + Number(t.quota).toLocaleString() + ' / month</b></div></section>';
    } catch (e) { v.innerHTML = '<div class="nx-empty">Could not load tenant: ' + esc(reason(e)) + '</div>'; }
  }
  function workflowNote() {
    const v = $('view-workflows'); if (!v || $('qfn-wf-note')) return;
    v.insertAdjacentHTML('afterbegin', '<div id="qfn-wf-note" class="section-note" style="margin-bottom:14px"><span style="color:var(--green)">●</span><div><b>Runs execute on the backend</b><span>Design the graph here; “Run” saves it as a versioned workflow (a new version only when the graph changes) and starts a durable run. Step jobs appear in Jobs and are executed by real workers.</span></div></div>');
  }

  function liveView(view) {
    if (view === 'Workers') renderLiveWorkers();
    else if (view === 'Audit Log') renderLiveAudit(true);
    else if (view === 'Security') renderLiveKeys();
    else if (view === 'Tenants') renderLiveTenant();
    else if (view === 'Workflows') workflowNote();
    liveTiles();
  }

  document.addEventListener('DOMContentLoaded', function () {
    installJobOverrides();
    const prevNav = window.navigate;
    window.navigate = function (view) {
      const r = prevNav.apply(this, arguments);
      if (live()) liveView(view);
      else ['pause-button', 'nexus-worker-create'].forEach((id) => { if ($(id)) $(id).style.display = ''; });
      return r;
    };
    const prevRender = window.renderJobs;
    window.renderJobs = function () { const r = prevRender.apply(this, arguments); liveTiles(); return r; };
    const prevSync = window.onQueueForgeLiveSync;
    window.onQueueForgeLiveSync = async function () {
      if (prevSync) await prevSync();
      liveTiles();
      if (['Workers', 'Tenants', 'Security'].includes(currentView())) liveView(currentView());
      if (currentView() === 'Audit Log') renderLiveAudit(true);
    };

    // Filters/search on the audit view keep working on the real events.
    document.addEventListener('input', (e) => { if (live() && e.target.id === 'nx-audit-search') renderLiveAudit(false); });
    document.addEventListener('change', (e) => { if (live() && e.target.id === 'nx-audit-filter') renderLiveAudit(false); });
    const auditHost = $('nx-audit-list');
    if (auditHost) { auditObserver = new MutationObserver(() => { if (live() && !auditWriting && currentView() === 'Audit Log') renderLiveAudit(false); }); auditObserver.observe(auditHost, { childList: true }); }

    // Capture on window = before the demo handlers on document.
    window.addEventListener('click', function (e) {
      if (!live()) return;
      const el = e.target.closest('[data-action],[data-nx]'); if (!el) return;
      const act = el.dataset.action, nx = el.dataset.nx;
      const stop = () => { e.preventDefault(); e.stopImmediatePropagation(); };
      if (act === 'workflow-run' || act === 'studio-run') {
        stop(); const w = selectedWorkflow(act === 'workflow-run' ? Number(el.dataset.index) : undefined); if (w) runLiveWorkflow(w); return;
      }
      if (nx === 'key-create') { stop(); createLiveKey(); return; }
      if (nx === 'key-revoke') {
        stop(); api('/keys/' + enc(el.dataset.id) + '/revoke', { method: 'POST' }).then(() => { say('Key revoked on the backend'); renderLiveKeys(); }).catch((x) => say('Could not revoke key: ' + reason(x))); return;
      }
      if (nx === 'audit-export' && auditCache) {
        stop(); const rows = [['id', 'created_at', 'kind', 'action', 'actor', 'detail']].concat(auditCache.map((x) => [x.id, x.created_at, x.kind, x.action, x.actor, x.detail]));
        const csv = rows.map((r) => r.map((v) => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"').join(',')).join('\r\n');
        const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'queueforge-audit.csv'; document.body.appendChild(a); a.click(); a.remove(); say('Backend audit log exported'); return;
      }
    }, true);

    // A live console should not need manual refreshes to see worker progress.
    setInterval(() => { if (live() && !document.hidden) window.__qfnLiveApi.sync(true); }, 5000);
  });
})();
