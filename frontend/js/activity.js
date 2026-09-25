/* Activity feed + event log. */
(() => {
  "use strict";

  const { $, fmtTime, escapeHtml } = window.UI;

  const DANGER_EVENTS = new Set([
    "NODE_FAILED", "CORRUPTION_DETECTED", "REPAIR_FAILED", "OBJECT_UNAVAILABLE",
  ]);
  const WARN_EVENTS = new Set([
    "NETWORK_PARTITION", "OBJECT_STATUS_CHANGED", "REPAIR_STARTED", "CORRUPTION_SIMULATED",
  ]);
  const OK_EVENTS = new Set([
    "OBJECT_UPLOADED", "REPLICA_CREATED", "REPLICA_REPAIRED", "REPAIR_COMPLETED",
    "NODE_RECOVERED", "CHECKSUM_VERIFIED", "REPLICA_RECONCILED", "REBALANCE_COMPLETED",
  ]);

  async function refreshFeed() {
    const el = $("#activity-feed");
    if (!el) return;
    try {
      const events = await window.VaultAPI.getActivity(40);
      el.innerHTML = events.map((event) => {
        const cls = DANGER_EVENTS.has(event.event_type) ? "ev-danger"
          : WARN_EVENTS.has(event.event_type) ? "ev-warn"
          : OK_EVENTS.has(event.event_type) ? "ev-ok" : "";
        return `<div class="feed-item ${cls}">
          <span class="feed-time">${fmtTime(event.created_at)}</span>
          <span class="feed-msg">${escapeHtml(event.message)}</span>
        </div>`;
      }).join("") || `<div class="empty"><span class="big">📡</span>No activity yet —
        system events will appear here as the cluster works.</div>`;
    } catch {
      el.innerHTML = `<div class="empty"><span class="big">⚠️</span>Unable to connect to backend.</div>`;
    }
  }

  async function refreshTable() {
    const tbody = $("#activity-tbody");
    if (!tbody) return;
    try {
      const events = await window.VaultAPI.getActivity(200);
      tbody.innerHTML = events.map((event) => `<tr>
        <td class="mono">${fmtTime(event.created_at)}</td>
        <td>${escapeHtml(event.event_type)}</td>
        <td>${escapeHtml(event.message)}</td>
        <td class="mono">${window.UI.shortId(event.object_id || "")}</td>
        <td class="mono">${escapeHtml(event.node_id || "—")}</td>
      </tr>`).join("") || `<tr><td colspan="5"><div class="empty"><span class="big">📡</span>
        No events yet — system activity will appear here.</div></td></tr>`;
    } catch {
      tbody.innerHTML = `<tr><td colspan="5"><div class="empty"><span class="big">⚠️</span>
        Unable to connect to backend.</div></td></tr>`;
    }
  }

  window.Activity = { refreshFeed, refreshTable };
})();
