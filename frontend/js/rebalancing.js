/* Rebalancing: utilization bars + movement history. */
(() => {
  "use strict";

  const { $, chip, escapeHtml, fmtBytes, toast } = window.UI;

  async function refresh() {
    try {
      const [stats, jobs] = await Promise.all([
        window.VaultAPI.getStats(),
        window.VaultAPI.getRebalanceJobs(),
      ]);
      renderBars(stats.per_node || []);
      const tbody = $("#rebalance-tbody");
      tbody.innerHTML = jobs.map((job) => `<tr>
        <td class="mono">${(job.filename || job.object_id).slice(0, 20)}</td>
        <td class="mono">${escapeHtml(job.source_node_id)}</td>
        <td class="mono">${escapeHtml(job.dest_node_id)}</td>
        <td class="mono">${fmtBytes(job.bytes_moved)}</td>
        <td><div class="bar"><div class="bar-fill" style="width:${job.progress}%"></div></div></td>
        <td>${chip(job.status)}</td>
      </tr>`).join("") || `<tr><td colspan="6"><div class="empty"><span class="big">⚖️</span>
        No rebalance movements yet — nodes are below the utilization threshold.</div></td></tr>`;
      $("#rebalance-summary").textContent =
        `${jobs.filter((j) => j.status === "COMPLETED").length} completed · ` +
        `${fmtBytes(jobs.reduce((sum, j) => j.status === "COMPLETED" ? sum + j.bytes_moved : sum, 0))} moved`;
    } catch (err) {
      console.warn("rebalance refresh failed", err);
    }
  }

  function renderBars(nodes) {
    $("#rebalance-bars").innerHTML = nodes.map((node) => {
      const util = node.utilization || 0;
      const fill = util > 85 ? "bad" : util > 60 ? "warn" : "";
      const over = util >= 80;
      return `<div class="util-row">
        <span class="label">${escapeHtml(node.node_id)}</span>
        <div class="bar"><div class="bar-fill ${fill}" style="width:${Math.min(util, 100)}%"></div></div>
        <span class="value">${util.toFixed(1)}% ${over ? "⚠" : ""}</span>
      </div>`;
    }).join("");
  }

  async function trigger() {
    try {
      const result = await window.VaultAPI.triggerRebalance();
      if (!result.planned) {
        toast(result.message || "No rebalancing needed — utilization within threshold", "ok");
      } else {
        toast(`Rebalanced: ${result.completed}/${result.planned} move(s) completed` +
          (result.failed ? ` · ${result.failed} failed` : ""), result.failed ? "err" : "ok");
      }
      await Promise.all([refresh(), window.Dashboard.refresh(), window.Topology.refresh()]);
    } catch (err) {
      toast(err.message, "err");
    }
  }

  window.Rebalancing = { refresh, trigger };
})();
