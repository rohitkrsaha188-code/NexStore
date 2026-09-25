/* Notifications: real system events from /api/activity, unread badge, navigation. */
(() => {
  "use strict";

  const { $, fmtTime, escapeHtml } = window.UI;
  const IMPORTANT = new Set([
    "NODE_FAILED", "NODE_RECOVERED", "NETWORK_PARTITION", "CORRUPTION_DETECTED",
    "REPAIR_STARTED", "REPAIR_COMPLETED", "REPAIR_FAILED", "REPLICA_REPAIRED",
    "REPLICA_CREATED", "OBJECT_UPLOADED", "REBALANCE_COMPLETED", "OBJECT_DELETED",
  ]);
  let seen = new Set();
  let items = [];

  function viewFor(eventType) {
    if (eventType.startsWith("REPAIR")) return "repairs";
    if (eventType.startsWith("REBALANCE")) return "rebalancing";
    if (eventType.startsWith("NODE") || eventType.startsWith("NETWORK")) return "nodes";
    if (eventType.startsWith("OBJECT") || eventType.startsWith("REPLICA")) return "objects";
    return "activity";
  }

  async function refresh(initial = false) {
    try {
      const events = (await window.VaultAPI.getActivity(20)).filter((e) => IMPORTANT.has(e.event_type));
      items = events;
      if (initial) {
        seen = new Set(events.map((e) => e.id));
        updateBadge();
      } else {
        updateBadge();
        render();
      }
    } catch { /* backend unreachable; keep last state */ }
  }

  function unreadCount() {
    return items.filter((e) => !seen.has(e.id)).length;
  }

  function updateBadge() {
    const count = unreadCount();
    const badge = $("#notif-count");
    badge.hidden = count === 0;
    badge.textContent = count > 9 ? "9+" : String(count);
  }

  function render() {
    const el = $("#notif-dropdown");
    el.innerHTML = items.length
      ? items.map((event) => `
          <div class="notif-item ${seen.has(event.id) ? "" : "unread"}" data-id="${event.id}">
            <div class="t">${escapeHtml(event.event_type.replaceAll("_", " "))}</div>
            <div class="m">${escapeHtml(event.message)}</div>
            <div class="time">${fmtTime(event.created_at)}</div>
          </div>`).join("")
      : `<div class="notif-item"><div class="m">No notifications yet — system events will appear here.</div></div>`;
    el.querySelectorAll(".notif-item[data-id]").forEach((node) =>
      node.addEventListener("click", () => {
        const id = Number(node.dataset.id);
        seen.add(id);
        updateBadge();
        el.classList.remove("open");
        window.app.switchView(viewFor(items.find((e) => e.id === id)?.event_type || ""));
      }));
  }

  function init() {
    const dropdown = $("#notif-dropdown");
    $("#btn-notifications")?.addEventListener("click", (event) => {
      event.stopPropagation();
      items.forEach((e) => seen.add(e.id));
      updateBadge();
      render();
      dropdown.classList.toggle("open");
      $("#user-dropdown").classList.remove("open");
    });
    document.addEventListener("click", () => dropdown?.classList.remove("open"));
    refresh(true);
    setInterval(() => refresh(false), 10000);
  }

  window.Notifications = { init, refresh };
})();
