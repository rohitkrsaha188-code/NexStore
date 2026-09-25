/* Repair center: metrics + job table. */
(() => {
  "use strict";

  const { $, chip, escapeHtml, fmtDuration, fmtDateTime, toast } = window.UI;

  async function refresh() {
    const tbody = $("#repairs-tbody");
    if (!tbody) return;
    try {
      const [jobs, metrics] = await Promise.all([
        window.VaultAPI.getRepairs(100),
        window.VaultAPI.getRepairMetrics(),
      ]);
      $("#repair-metrics").innerHTML = [
        ["ACTIVE JOBS", metrics.queued + metrics.running, "queued + running"],
        ["COMPLETED", metrics.completed, `avg ${fmtDuration(metrics.avg_recovery_ms)}`],
        ["FAILED", metrics.failed, "needs attention"],
        ["TOTAL", metrics.total, "all time"],
      ].map(([label, value, sub]) => `
        <article class="stat-card">
          <h3>${label}</h3><div class="stat-value">${value}</div><div class="stat-sub">${sub}</div>
        </article>`).join("");

      tbody.innerHTML = jobs.map((job) => `<tr>
        <td><strong>${escapeHtml(job.filename)}</strong>
            <span class="mono" style="color:var(--muted); font-size:.7rem">${job.object_id.slice(0, 12)}…</span></td>
        <td class="mono">${job.failed_node_id || "—"}</td>
        <td class="mono">${job.replacement_node_id || "—"}</td>
        <td>${escapeHtml(job.reason)}</td>
        <td class="mono">${fmtDateTime(job.started_at)}</td>
        <td class="mono">${fmtDuration(job.duration_ms)}</td>
        <td><div class="bar"><div class="bar-fill" style="width:${job.progress}%"></div></div></td>
        <td>${chip(job.status)}</td>
        <td>${job.status === "FAILED"
          ? `<button class="btn btn-sm" data-retry="${job.repair_id}">Retry</button>` : ""}</td>
      </tr>`).join("") || `<tr><td colspan="9"><div class="empty"><span class="big">🛡️</span>
        No repair jobs — all replicas are currently healthy.</div></td></tr>`;

      $$("button[data-retry]", tbody).forEach((button) => {
        button.addEventListener("click", async () => {
          try {
            await window.VaultAPI.retryRepair(button.dataset.retry);
            toast("Repair re-queued", "ok");
            await refresh();
          } catch (err) {
            toast(err.message, "err");
          }
        });
      });
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="9"><div class="empty"><span class="big">⚠️</span>
        Unable to load repairs: ${escapeHtml(err.message)} — check that the backend is running.</div></td></tr>`;
    }
  }

  window.Repairs = { refresh };
})();
