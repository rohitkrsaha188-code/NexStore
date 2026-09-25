/* Shared UI helpers: formatting, chips, toasts. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  function fmtBytes(n) {
    if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
    const units = ["B", "KB", "MB", "GB", "TB", "PB"];
    let value = Number(n);
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return `${value >= 100 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString([], { hour12: false });
  }

  function fmtDateTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString([], { hour12: false });
  }

  function fmtDuration(ms) {
    if (ms === null || ms === undefined) return "—";
    if (ms < 1000) return `${ms} ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
    return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
  }

  const CHIP_CLASS = {
    ONLINE: "chip-ok", HEALTHY: "chip-ok", VERIFIED: "chip-ok", COMPLETED: "chip-ok",
    CONNECTED: "chip-ok",
    DEGRADED: "chip-warn", REPAIRING: "chip-warn", QUEUED: "chip-warn", RUNNING: "chip-info",
    VERIFYING: "chip-info", STALE: "chip-warn", PARTITIONED: "chip-warn", REBALANCING: "chip-purple",
    FAILED: "chip-bad", CORRUPTED: "chip-bad", MISSING: "chip-bad", UNAVAILABLE: "chip-bad",
    OFFLINE: "chip-muted", CANCELLED: "chip-muted", OBSOLETE: "chip-muted", FAILED_JOB: "chip-bad",
  };

  function chip(status) {
    const cls = CHIP_CLASS[status] || "chip-muted";
    return `<span class="chip ${cls}">${escapeHtml(String(status || "—"))}</span>`;
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
  }

  function toast(message, kind = "") {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.className = `toast ${kind}`;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, 3500);
  }

  function shortId(id) {
    if (!id) return "—";
    return id.length > 18 ? `${id.slice(0, 14)}…${id.slice(-4)}` : id;
  }

  window.UI = { $, $$, fmtBytes, fmtTime, fmtDateTime, fmtDuration, chip, escapeHtml, toast, shortId };
})();
