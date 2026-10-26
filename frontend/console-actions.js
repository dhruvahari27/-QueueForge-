/*
 * Operational controls shared by the static console and the live API bridge.
 * The console remains useful without a backend, while connected controls perform
 * the matching API operation instead of mutating illustrative browser state.
 */
(function () {
  'use strict';

  const byId = (id) => document.getElementById(id);
  const isLive = () => Boolean(window.__qfnLive && window.__qfnLive.connected && window.__qfnLiveApi);
  const announce = (message) => window.toast ? window.toast(message) : window.alert(message);
  const escapeHtml = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

  function downloadCsv(filename, rows) {
    const csv = rows.map((row) => row.map((value) => '"' + String(value).replace(/"/g, '""') + '"').join(',')).join('\r\n');
    const link = document.createElement('a');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  window.refreshData = async function refreshData() {
    if (isLive()) {
      await window.__qfnLiveApi.sync(false);
      return;
    }
    if (byId('jobs-table') && typeof window.renderJobs === 'function') window.renderJobs();
    if (byId('workers-grid') && typeof window.renderWorkers === 'function') window.renderWorkers();
    if (byId('workflow-cards') && typeof window.renderWorkflows === 'function') window.renderWorkflows();
    const updated = document.querySelector('.updated');
    if (updated) updated.innerHTML = '<i class="green-dot"></i> Demo data refreshed just now';
    announce('Illustrative dashboard data refreshed');
  };

  window.exportChartData = function exportChartData() {
    const points = [26, 32, 28, 41, 36, 48, 42, 57, 48, 62, 56, 72, 64, 80, 70, 88, 77, 93, 84, 76, 88, 80, 96, 82];
    downloadCsv('queueforge-demo-throughput.csv', [['interval', 'relative_throughput']].concat(points.map((value, index) => [index + 1, value])));
    announce('Illustrative throughput CSV exported');
  };

  const originalRetryJob = window.retryJob;
  window.retryJob = async function retryJob(id) {
    if (!isLive()) return originalRetryJob(id);
    try {
      await window.__qfnLiveApi.request('/jobs/' + encodeURIComponent(id) + '/retry', {
        method: 'POST', body: JSON.stringify({ reason: 'console_retry' })
      });
      await window.__qfnLiveApi.sync(true);
      if (typeof window.openJob === 'function') window.openJob(id);
      announce('Job retry requested from the live backend');
    } catch (error) {
      announce('Could not retry job: ' + (error.message || error));
    }
  };

  async function runWorkflow(workflowId, fallbackCard) {
    if (!isLive()) {
      const count = fallbackCard && fallbackCard.querySelector('.wf-stats div:nth-child(2) b');
      if (count) count.textContent = (Number(count.textContent.replace(/,/g, '')) + 1).toLocaleString();
      announce('Illustrative workflow run queued locally. Connect a backend to persist it.');
      return;
    }
    try {
      const result = await window.__qfnLiveApi.request('/workflows/' + encodeURIComponent(workflowId) + '/runs', { method: 'POST' });
      await window.__qfnLiveApi.sync(true);
      announce('Workflow run started: ' + (result.data.id || 'created'));
    } catch (error) {
      announce('Could not start workflow: ' + (error.message || error));
    }
  }
  window.runWorkflow = runWorkflow;

  function renderLiveWorkflows(items) {
    const target = byId('workflow-cards');
    if (!target) return;
    target.innerHTML = items.length ? items.map((workflow) => {
      const graph = workflow.graph || {};
      const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
      const runs = workflow.run_count == null ? '—' : String(workflow.run_count);
      return '<section class="panel workflow-card" data-workflow-id="' + escapeHtml(workflow.id) + '"><div class="wf-card-top"><div class="wf-icon mint">⑂</div><span class="status success">live</span></div><h3>' + escapeHtml(workflow.name) + '</h3><p>' + escapeHtml(workflow.description || 'No description provided.') + '</p><div class="workflow-nodes">' + nodes.map((_, index) => '<span>' + (index + 1) + '</span>').join('') + '</div><div class="wf-stats"><div><span>VERSION</span><b>v' + escapeHtml(workflow.version || 1) + '</b></div><div><span>TOTAL RUNS</span><b>' + escapeHtml(runs) + '</b></div><div><span>TASKS</span><b>' + nodes.length + '</b></div></div><button class="btn btn-primary run-btn" data-live-workflow="' + escapeHtml(workflow.id) + '">▶ Run workflow <span>→</span></button></section>';
    }).join('') : '<div class="nx-empty">No workflows exist in this tenant yet. Create one through the API Explorer, then refresh.</div>';
  }

  window.onQueueForgeLiveSync = async function onQueueForgeLiveSync() {
    if (!isLive()) return;
    try {
      const result = await window.__qfnLiveApi.request('/workflows');
      const items = Array.isArray(result.data) ? result.data : (result.data.items || []);
      renderLiveWorkflows(items);
    } catch (_) {
      // Workflow scopes are optional for a jobs-only API key; leave the current
      // cards visible and avoid treating a scope restriction as a connection error.
    }
  };

  document.addEventListener('DOMContentLoaded', function () {
    const refreshButton = document.querySelector('.heading-actions .btn-secondary');
    if (refreshButton) refreshButton.onclick = () => window.refreshData();

    // These controls previously advertised work that had not been implemented.
    // Exporting/navigating gives every visible control a safe, useful outcome.
    document.addEventListener('click', function (event) {
      const button = event.target.closest('button');
      if (!button) return;
      if (button.matches('.run-btn')) {
        event.preventDefault();
        event.stopImmediatePropagation();
        const card = button.closest('.workflow-card');
        void runWorkflow(button.dataset.liveWorkflow || '', card);
        return;
      }
      if (button.closest('.workflow-card') && button.matches('.wf-card-top .icon-button')) {
        event.preventDefault();
        event.stopImmediatePropagation();
        const card = button.closest('.workflow-card');
        announce(card.querySelector('h3').textContent + ' · inspect it in the Workflow studio or run it from this card.');
        return;
      }
      const label = button.textContent.trim();
      if (label === '···' && button.closest('.chart-actions')) {
        event.preventDefault();
        event.stopImmediatePropagation();
        window.exportChartData();
      }
    }, true);
  });
})();
