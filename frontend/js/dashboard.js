/* Dashboard: stat cards, utilization, storage overhead. */
(() => {
  "use strict";

  const { $, fmtBytes, chip } = window.UI;

  async function refresh() {
    try {
      const stats = await window.VaultAPI.getStats();
      renderStats(stats);
      renderUtilization(stats.per_node || []);
      renderOverhead(stats);
      renderHealthPill(stats);
      window.app?.refreshBadge(stats);
    } catch (err) {
      console.warn("stats refresh failed", err);
    }
  }

  function renderStats(s) {
    $("#stat-total").textContent = fmtBytes(s.total_capacity);
    $("#stat-used").textContent = fmtBytes(s.used_capacity);
    const pct = s.total_capacity ? Math.round(100 * s.used_capacity / s.total_capacity) : 0;
    $("#stat-used-pct").textContent = `${pct}% of cluster`;
    $("#stat-available").textContent = fmtBytes(s.available_capacity);
    $("#stat-nodes-online").textContent = `${s.nodes_online}/${s.nodes_total}`;
    $("#stat-nodes-sub").textContent =
      `${s.nodes_failed} failed · ${s.nodes_partitioned} partitioned`;
    $("#stat-nodes-failed").textContent = s.nodes_failed + s.nodes_partitioned;
    $("#stat-objects").textContent = s.total_objects.toLocaleString();
    $("#stat-replicas-sub").textContent = `${s.total_replicas} replicas · RF=${s.replication_factor}`;
    $("#stat-repairs").textContent = s.active_repair_jobs;
    $("#stat-repairs-sub").textContent =
      `${s.completed_repairs} completed · ${s.failed_repairs} failed`;
    $("#stat-rf").textContent = `${s.replication_factor}×`;
    const overheadPct = s.logical_storage
      ? Math.round(100 * s.replication_overhead / s.logical_storage) : 0;
    $("#stat-overhead-sub").textContent =
      `overhead ${fmtBytes(s.replication_overhead)} (+${overheadPct}%)`;
  }

  function renderHealthPill(s) {
    const pill = $("#system-health-pill");
    pill.className = "pill";
    if (s.system_health === "HEALTHY") {
      pill.classList.add("pill-ok");
      pill.innerHTML = `<span class="dot"></span> SYSTEM HEALTHY`;
    } else if (s.system_health === "DEGRADED") {
      pill.classList.add("pill-warn");
      pill.innerHTML = `<span class="dot"></span> SYSTEM DEGRADED`;
    } else {
      pill.classList.add("pill-bad");
      pill.innerHTML = `<span class="dot"></span> SYSTEM CRITICAL`;
    }
  }

  function renderUtilization(nodes) {
    const el = $("#util-bars");
    if (!el) return;
    el.innerHTML = nodes.map((node) => {
      const util = node.utilization || 0;
      const fill = util > 85 ? "bad" : util > 60 ? "warn" : "";
      return `<div class="util-row">
        <span class="label">${escapeHtml(node.node_id)}</span>
        <div class="bar"><div class="bar-fill ${fill}" style="width:${Math.min(util, 100)}%"></div></div>
        <span class="value">${util.toFixed(1)}% · ${fmtBytes(node.used_capacity)}</span>
      </div>`;
    }).join("") || `<div class="empty">No nodes</div>`;
  }

  function renderOverhead(s) {
    const el = $("#overhead");
    if (!el) return;
    const rows = [
      ["Logical storage (unique data)", fmtBytes(s.logical_storage)],
      ["Physical storage (replicated)", fmtBytes(s.physical_storage)],
      ["Replication overhead", fmtBytes(s.replication_overhead)],
      ["Replication factor", `${s.replication_factor}×`],
    ];
    el.innerHTML = rows.map(([k, v]) =>
      `<div class="overhead-row"><span class="k">${k}</span><span class="v">${v}</span></div>`
    ).join("");
  }

  window.Dashboard = { refresh };
})();
