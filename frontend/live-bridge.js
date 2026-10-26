/* QueueForge Nexus live API bridge.
 * Live mode is opt-in; the preview remains explicitly demo-only until a backend is reachable.
 * API tokens are held in sessionStorage for this tab, never embedded in source or localStorage.
 */
(function () {
  'use strict';
  const URL_KEY = 'qfn_live_api_url_v1';
  const TOKEN_KEY = 'qfn_live_api_token_v1';
  const live = window.__qfnLive = { connected: false, baseUrl: '', token: '', lastError: '', syncing: false, dashboard: null };
  const $id = (id) => document.getElementById(id);
  const readSession = (key) => { try { return sessionStorage.getItem(key) || ''; } catch (_) { return ''; } };
  const writeSession = (key, value) => { try { if (value) sessionStorage.setItem(key, value); else sessionStorage.removeItem(key); } catch (_) {} };
  live.baseUrl = readSession(URL_KEY);
  live.token = readSession(TOKEN_KEY);

  function cleanBase(value) { return String(value || '').trim().replace(/\/+$/, ''); }
  function joinPath(path) {
    let p = String(path || '').trim();
    if (!p.startsWith('/')) p = '/' + p;
    if (p.startsWith('/v1/')) p = p.slice(3);
    if (p === '/v1') p = '/';
    if (p === '/api' || p.startsWith('/api/')) p = p.slice(4) || '/';
    return cleanBase(live.baseUrl) + p;
  }
  async function request(path, options) {
    const opts = Object.assign({ method: 'GET', headers: {} }, options || {});
    opts.headers = Object.assign({ 'Accept': 'application/json' }, opts.headers || {});
    if (live.token) opts.headers.Authorization = 'Bearer ' + live.token;
    if (opts.body && !opts.headers['Content-Type']) opts.headers['Content-Type'] = 'application/json';
    const resp = await fetch(joinPath(path), opts);
    const text = await resp.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { raw: text }; }
    if (!resp.ok) {
      const message = data && (data.detail || data.message || data.error) || ('HTTP ' + resp.status);
      const error = new Error(String(message)); error.status = resp.status; error.data = data; throw error;
    }
    return { status: resp.status, data: data };
  }
  function toMs(value) { if (!value) return null; if (typeof value === 'number') return value < 1e12 ? value * 1000 : value; let v = String(value); if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(v) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(v)) v += 'Z'; const n = Date.parse(v); return Number.isFinite(n) ? n : null; }
  function normalizeJob(j) {
    const status = j.status === 'failed' ? 'dead' : j.status;
    return { id: j.id, tenant_id: j.tenant_id, task_type: j.task_type, queue: j.queue || 'default', status: status,
      priority: Number(j.priority ?? 5), payload: j.payload || {}, result: j.result || null, error: j.error || null,
      attempts_count: Number(j.attempts_count ?? 0), max_attempts: Number(j.max_attempts ?? 3), worker_id: j.worker_id || null,
      created_at: toMs(j.created_at) || Date.now(), started_at: toMs(j.started_at), finished_at: toMs(j.finished_at),
      lease_expires_at: toMs(j.lease_expires_at), workflow_run_id: j.workflow_run_id || null };
  }
  function showMode(isLive, detail) {
    // There are separate indicators in the header and jobs toolbar; keep them in sync.
    document.querySelectorAll('.api-indicator').forEach((indicator) => {
      indicator.innerHTML = '<i class="' + (isLive ? 'green-dot' : 'amber-dot') + '"></i> ' + (isLive ? 'Live API connected' : 'Demo environment');
      indicator.title = detail || (isLive ? 'Jobs loaded from the configured backend.' : 'No backend connection is active.');
    });
    let badge = $id('qfn-live-mode-banner');
    const overview = $id('view-overview');
    if (overview && isLive) {
      if (!badge) {
        badge = document.createElement('div'); badge.id = 'qfn-live-mode-banner'; badge.className = 'section-note'; badge.style.marginBottom = '14px';
        overview.insertBefore(badge, overview.firstChild);
      }
      badge.innerHTML = '<span style="color:var(--green)">●</span><div><b>Connected to live backend</b><span>Job records are being fetched from ' + escapeHtml(live.baseUrl) + '. Charts and other service health figures remain illustrative unless their endpoints are explicitly connected.</span></div>';
    } else if (badge) badge.remove();
  }
  function escapeHtml(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function setStatus(text, ok) {
    const el = $id('qfn-live-status'); if (!el) return;
    el.textContent = text; el.style.color = ok ? 'var(--green)' : (text.toLowerCase().includes('connect') || text.toLowerCase().includes('error') || text.toLowerCase().includes('failed') ? 'var(--red)' : 'var(--muted)');
  }
  function ensurePanel() {
    if (!$id('qfn-live-mobile-fix')) {
      const mobileStyle = document.createElement('style'); mobileStyle.id = 'qfn-live-mobile-fix';
      mobileStyle.textContent = '@media(max-width:760px){#qfn-live-settings-panel .setting-control{flex-direction:column;align-items:stretch;gap:9px}#qfn-live-settings-panel input{width:100%!important;min-width:0!important}}';
      document.head.appendChild(mobileStyle);
    }
    const target = $id('view-settings');
    if (!target || $id('qfn-live-settings-panel')) return;
    const panel = document.createElement('section'); panel.id = 'qfn-live-settings-panel'; panel.className = 'panel settings-panel'; panel.style.marginBottom = '14px';
    panel.innerHTML = '<div class="panel-head"><div><h2>Live backend connection</h2><p>Connect the UI to a running QueueForge API. This is an actual HTTP connection, unlike the in-page simulators.</p></div><span class="status queued" id="qfn-live-state">Not connected</span></div>' +
      '<div class="settings-controls"><div class="setting-control"><div><b>API base URL</b><small>Use /api for the same-origin proxy, or a full URL for a separately hosted API.</small></div><input id="qfn-live-url" type="text" inputmode="url" placeholder="/api or https://api.example.com/api" style="width:min(52%,390px);min-width:210px" autocomplete="url"></div>' +
      '<div class="setting-control"><div><b>Bearer API key (optional in development)</b><small>Kept in this tab’s session storage. Never paste a production key into a shared demo.</small></div><input id="qfn-live-token" type="password" placeholder="qfn_live_…" style="width:min(52%,390px);min-width:210px" autocomplete="off" spellcheck="false"></div>' +
      '<div class="action-strip" style="margin:15px 0 8px"><button class="btn btn-primary" id="qfn-live-connect">Connect & sync jobs</button><button class="btn btn-secondary" id="qfn-live-sync">Refresh live data</button><button class="btn btn-secondary" id="qfn-live-disconnect">Disconnect</button></div><div id="qfn-live-status" role="status" aria-live="polite" style="font-size:10px;color:var(--muted);line-height:1.7">Not connected. The preview will continue to use clearly labelled demo data.</div>' +
      '<div class="dialog-note">Recommended for Compose: use <b>/api</b> so requests stay same-origin through Nginx. For a separately hosted API, use its full HTTPS base URL and allow its exact origin in both backend CORS and this frontend CSP. Do not expose an unauthenticated development API to the public internet.</div></div>';
    target.insertBefore(panel, target.firstChild);
    $id('qfn-live-url').value = live.baseUrl || '/api';
    $id('qfn-live-token').value = live.token || '';
    $id('qfn-live-connect').addEventListener('click', () => connectAndSync(false));
    $id('qfn-live-sync').addEventListener('click', () => syncLiveData(false));
    $id('qfn-live-disconnect').addEventListener('click', disconnect);
    updateConnectionBadge();
  }
  function updateConnectionBadge() {
    const state = $id('qfn-live-state');
    if (state) { state.textContent = live.connected ? 'Live API connected' : 'Not connected'; state.className = 'status ' + (live.connected ? 'success' : 'queued'); }
    showMode(live.connected);
  }
  async function connectAndSync(silent) {
    const url = cleanBase($id('qfn-live-url') ? $id('qfn-live-url').value : live.baseUrl);
    const token = $id('qfn-live-token') ? $id('qfn-live-token').value.trim() : live.token;
    const sameOriginApi = url.startsWith('/api') && !url.startsWith('//');
    if (!sameOriginApi && !/^https?:\/\//i.test(url)) { setStatus('Enter /api for the same-origin proxy, or a full http:// or https:// API URL.', false); return; }
    live.baseUrl = url; live.token = token; live.connected = false;
    writeSession(URL_KEY, url); writeSession(TOKEN_KEY, token); updateConnectionBadge();
    const connectButton = $id('qfn-live-connect'); if (connectButton) { connectButton.disabled = true; connectButton.textContent = 'Connecting…'; }
    setStatus('Checking backend readiness and permissions…', false);
    try {
      const health = await request('/health');
      if (!health.data || !['ready', 'ok', 'healthy'].includes(String(health.data.status || '').toLowerCase())) throw new Error('Backend health response was not ready.');
      // A health endpoint alone does not prove authorized access to real data.
      const jobsResult = await request('/jobs?limit=250');
      const list = Array.isArray(jobsResult.data) ? jobsResult.data : (jobsResult.data.items || jobsResult.data.jobs || []);
      if (!Array.isArray(list)) throw new Error('The jobs endpoint response did not contain an items array.');
      live.connected = true; live.lastError = ''; applyJobs(list);
      try { live.dashboard = (await request('/dashboard')).data; updateDashboard(live.dashboard); } catch (_) { live.dashboard = null; }
      if (typeof window.onQueueForgeLiveSync === 'function') await window.onQueueForgeLiveSync();
      updateConnectionBadge(); setStatus('Connected. Loaded ' + list.length + ' real job record(s); API readiness and job authorization both passed.', true);
      if (!silent && typeof window.toast === 'function') window.toast('Live API connected · ' + list.length + ' jobs loaded');
    } catch (error) {
      live.connected = false; live.lastError = error.message || String(error); try { jobs = seed.map((j) => Object.assign({}, j)); if (typeof window.renderJobs === 'function') window.renderJobs(); } catch (_) {}
      if ($id('metric-processed')) $id('metric-processed').textContent = '12,840'; if ($id('active-workers')) $id('active-workers').textContent = '18 / 24'; if ($id('obs-failed')) $id('obs-failed').textContent = '23';
      updateConnectionBadge(); setStatus('Connection failed: ' + live.lastError + '. Check API URL, authentication, server state, and CORS.', false);
      if (!silent && typeof window.toast === 'function') window.toast('Backend connection failed · ' + live.lastError);
    } finally {
      if (connectButton) { connectButton.disabled = false; connectButton.textContent = 'Connect & sync jobs'; }
    }
  }
  function applyJobs(list) {
    try {
      jobs = list.map(normalizeJob);
      if (typeof window.renderJobs === 'function') window.renderJobs();
      if (typeof window.renderEventFeeds === 'function') window.renderEventFeeds();
    } catch (error) { console.error('Unable to apply live QueueForge jobs', error); }
  }
  function updateDashboard(data) {
    if (!data || !data.job_counts) return;
    const counts = data.job_counts;
    const processed = $id('metric-processed'); if (processed) processed.textContent = String(data.total_jobs ?? Object.values(counts).reduce((a,b)=>a+b,0));
    const active = $id('active-workers'); if (active) active.textContent = String(data.active_workers ?? '—');
    const failed = $id('obs-failed'); if (failed) failed.textContent = String(counts.dead ?? 0);
    const banner = $id('qfn-live-mode-banner'); if (banner) banner.querySelector('span:last-child').textContent = 'Jobs and summary counts are from the connected backend. Latency charts, third-party dependencies, and telemetry must have dedicated endpoints before being treated as live.';
  }
  async function syncLiveData(silent) {
    if (live.syncing) return;
    if (!live.baseUrl || !live.connected) { if (!silent) await connectAndSync(false); return; }
    live.syncing = true; setStatus('Refreshing job records…', true);
    try {
      const result = await request('/jobs?limit=250'); const list = Array.isArray(result.data) ? result.data : (result.data.items || result.data.jobs || []);
      applyJobs(list);
      try { live.dashboard = (await request('/dashboard')).data; updateDashboard(live.dashboard); } catch (_) {}
      if (typeof window.onQueueForgeLiveSync === 'function') await window.onQueueForgeLiveSync();
      setStatus('Updated ' + list.length + ' live job record(s) at ' + new Date().toLocaleTimeString() + '.', true);
      if (!silent && typeof window.toast === 'function') window.toast('Live data refreshed');
    } catch (error) {
      live.connected = false; live.lastError = error.message || String(error); try { jobs = seed.map((j) => Object.assign({}, j)); if (typeof window.renderJobs === 'function') window.renderJobs(); } catch (_) {}
      if ($id('metric-processed')) $id('metric-processed').textContent = '12,840'; if ($id('active-workers')) $id('active-workers').textContent = '18 / 24'; if ($id('obs-failed')) $id('obs-failed').textContent = '23';
      updateConnectionBadge(); setStatus('Live refresh failed: ' + live.lastError, false);
      if (!silent && typeof window.toast === 'function') window.toast('Live refresh failed');
    } finally { live.syncing = false; }
  }
  // Deliberately small public surface for optional console controls. It keeps all
  // authenticated requests and URL construction in this module.
  window.__qfnLiveApi = {
    request: request,
    sync: syncLiveData,
    isConnected: function () { return live.connected; }
  };
  function disconnect() {
    live.connected = false; live.dashboard = null; live.lastError = ''; live.token = ''; live.baseUrl = '';
    writeSession(URL_KEY, ''); writeSession(TOKEN_KEY, '');
    try { jobs = seed.map((j) => Object.assign({}, j)); if (typeof window.renderJobs === 'function') window.renderJobs(); } catch (_) {}
    if ($id('metric-processed')) $id('metric-processed').textContent = '12,840'; if ($id('active-workers')) $id('active-workers').textContent = '18 / 24'; if ($id('obs-failed')) $id('obs-failed').textContent = '23';
    if ($id('qfn-live-token')) $id('qfn-live-token').value = '';
    updateConnectionBadge(); setStatus('Disconnected. Showing the original illustrative demo records again.', true);
    if (typeof window.toast === 'function') window.toast('Disconnected from backend');
  }
  async function createJobThroughAPI() {
    if (!live.connected) return false;
    let payload;
    try { payload = JSON.parse($id('task-payload').value); if (!payload || Array.isArray(payload) || typeof payload !== 'object') throw Error(); }
    catch (_) { if (typeof window.toast === 'function') window.toast('Payload must be a valid JSON object'); return true; }
    const body = { task_type: $id('task-type').value, queue: $id('task-queue').value, priority: Number($id('task-priority').value || 5), max_attempts: Number($id('task-attempts').value || 3), payload };
    try {
      const key = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : 'qfn-' + Date.now() + '-' + Math.random().toString(16).slice(2);
      const result = await request('/jobs', { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body) });
      if (typeof window.closeCreate === 'function') window.closeCreate();
      if (typeof window.navigate === 'function') window.navigate('Jobs');
      await syncLiveData(true);
      if (typeof window.toast === 'function') window.toast('Job persisted by backend · ' + (result.data.id || 'created'));
    } catch (error) { if (typeof window.toast === 'function') window.toast('Job was not created: ' + (error.message || error)); }
    return true;
  }
  function mapExplorerPath(path) {
    let p = String(path || '/v1/jobs').trim();
    if (p.startsWith('/v1')) p = p.slice(3) || '/';
    if (p === '/api' || p.startsWith('/api/')) p = p.slice(4) || '/';
    return p;
  }
  async function sendExplorerRequest() {
    const method = ($id('nx-method').value || 'GET').toUpperCase();
    const path = mapExplorerPath($id('nx-path').value);
    let body;
    if (!['GET','HEAD'].includes(method)) {
      try { body = JSON.parse($id('nx-body').value || '{}'); } catch (_) { if (window.toast) window.toast('Request body must be valid JSON'); return; }
    }
    const badge = $id('nx-response-badge'); const output = $id('nx-response'); const caption = $id('nx-response-caption');
    try {
      const result = await request(path, { method: method, body: body === undefined ? undefined : JSON.stringify(body) });
      output.textContent = JSON.stringify({ status: result.status, mode: 'live-backend', path: path, data: result.data }, null, 2);
      badge.textContent = 'HTTP ' + result.status + ' · live'; badge.className = 'status success'; caption.textContent = 'Actual HTTP response from ' + live.baseUrl;
      if (window.toast) window.toast('Live API request completed');
    } catch (error) {
      output.textContent = JSON.stringify({ status: error.status || 0, mode: 'live-backend', path: path, error: error.message, response: error.data || null }, null, 2);
      badge.textContent = (error.status || 'ERR') + ' · live'; badge.className = 'status danger'; caption.textContent = 'Live request failed; details shown below.';
      if (window.toast) window.toast('Live API request failed: ' + error.message);
    }
  }
  function installPageObserver() {
    const target = $id('view-settings'); if (!target) return;
    new MutationObserver(() => ensurePanel()).observe(target, { childList: true, subtree: true });
    ensurePanel();
  }
  document.addEventListener('DOMContentLoaded', function () {
    // Registered after the original page bootstrap, so the panel survives renderSettings().
    installPageObserver(); ensurePanel(); updateConnectionBadge();
    const refresh = document.querySelector('.heading-actions .btn-secondary');
    if (refresh) refresh.onclick = () => live.connected ? syncLiveData(false) : (typeof window.refreshData === 'function' ? window.refreshData() : window.toast && window.toast('No backend connected; preview data is illustrative.'));
    const originalCreateJob = window.createJob;
    if (typeof originalCreateJob === 'function') window.createJob = async function () { if (live.connected) return createJobThroughAPI(); return originalCreateJob(); };
    document.addEventListener('click', function (event) {
      const apiSend = event.target.closest('[data-nx="api-send"]');
      if (apiSend && live.connected) { event.preventDefault(); event.stopImmediatePropagation(); sendExplorerRequest(); return; }
      const action = event.target.closest('[data-action]');
      if (action && live.connected && action.dataset.action === 'job-cancel') {
        const id = action.dataset.id; request('/jobs/' + encodeURIComponent(id) + '/cancel', { method: 'POST', body: JSON.stringify({ reason: 'operator_cancel' }) })
          .then(() => syncLiveData(true)).catch((err) => window.toast && window.toast('Backend cancel failed: ' + err.message));
      }
      if (action && live.connected && action.dataset.action === 'job-duplicate') {
        const old = (typeof jobs !== 'undefined') ? jobs.find((j) => j.id === action.dataset.id) : null;
        if (old) request('/jobs', { method: 'POST', body: JSON.stringify({ task_type: old.task_type, queue: old.queue, priority: old.priority, max_attempts: old.max_attempts, payload: old.payload || {} }), headers: { 'Idempotency-Key': 'duplicate-' + Date.now() + '-' + Math.random().toString(16).slice(2) } }).then(() => syncLiveData(true)).catch((err) => window.toast && window.toast('Backend duplicate failed: ' + err.message));
      }
    }, true);
    if (live.baseUrl) { const t = setTimeout(() => { if (!live.connected && $id('qfn-live-url')) connectAndSync(true); }, 150); void t; }
  });
})();
