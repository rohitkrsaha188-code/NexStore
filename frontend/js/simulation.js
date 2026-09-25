/* Failure simulator panel: every action calls the real backend. */
(() => {
  "use strict";

  const { $, $$, toast } = window.UI;

  async function refreshNodePicker() {
    const picker = $("#sim-node");
    if (!picker) return;
    const previous = picker.value;
    try {
      const nodes = await window.VaultAPI.getNodes();
      picker.innerHTML = nodes.map((node) =>
        `<option value="${node.node_id}">${node.name} — ${node.status}</option>`
      ).join("");
      if (previous && nodes.some((node) => node.node_id === previous)) {
        picker.value = previous;
      }
    } catch { /* picker refresh is best-effort */ }
  }

  function showResult(message, kind = "") {
    const el = $("#sim-result");
    el.className = `sim-result ${kind}`;
    el.textContent = message;
  }

  async function runAction(action) {
    const nodeId = $("#sim-node").value;
    showResult("⏳ working…");
    try {
      let message = "";
      switch (action) {
        case "fail": {
          const result = await window.VaultAPI.failNode(nodeId);
          message = `● ${result.message}`;
          break;
        }
        case "restore": {
          const result = await window.VaultAPI.restoreNode(nodeId);
          message = `● ${result.message}`;
          break;
        }
        case "partition": {
          const result = await window.VaultAPI.partitionNode(nodeId);
          message = `● ${result.message}`;
          break;
        }
        case "reconnect": {
          const result = await window.VaultAPI.reconnectNode(nodeId);
          message = `● ${result.message}`;
          break;
        }
        case "corrupt": {
          const files = await window.VaultAPI.getFiles();
          if (!files.length) throw new Error("Upload an object first");
          let done = null;
          for (const file of files) {
            try {
              done = await window.VaultAPI.corruptObjectReplica(file.object_id, nodeId || undefined);
              break;
            } catch { /* try next object */ }
          }
          if (!done) throw new Error("No corruptible replica found");
          message = done.detected
            ? `● Corruption injected on ${done.node_id} — CHECKSUM MISMATCH detected, repair scheduled`
            : `● Corruption injected on ${done.node_id} — awaiting detection (integrity scan)`;
          break;
        }
        case "scan": {
          const result = await window.VaultAPI.integrityScan();
          message = `● Scanned ${result.replicas_checked} replicas: ` +
            `${result.verified} verified, ${result.corrupted} corrupted, ` +
            `${result.repairs_scheduled} repair(s) scheduled`;
          break;
        }
        case "rebalance": {
          const result = await window.VaultAPI.triggerRebalance();
          message = result.planned
            ? `● ${result.completed}/${result.planned} move(s) completed, ${result.failed} failed`
            : `● ${result.message || "No rebalancing needed"}`;
          break;
        }
        case "repair-now": {
          const metrics = await window.VaultAPI.getRepairMetrics();
          message = `● Repair worker active: ${metrics.queued} queued, ${metrics.running} running, ` +
            `${metrics.completed} completed all-time (avg recovery ${metrics.avg_recovery_ms ?? "—"} ms)`;
          break;
        }
        default:
          return;
      }
      showResult(message, "ok");
      await refreshAllViews();
    } catch (err) {
      showResult(`✗ ${err.message}`, "err");
      toast(err.message, "err");
    } finally {
      await refreshNodePicker();
    }
  }

  async function refreshAllViews() {
    await Promise.all([
      window.Dashboard.refresh(),
      window.Topology.refresh(),
      window.Nodes.refresh(),
      window.Files.refresh(),
      window.Replication.refresh(),
      window.Repairs.refresh(),
      window.Rebalancing.refresh(),
      window.Activity.refreshFeed(),
      window.Activity.refreshTable(),
    ]);
  }

  function init() {
    $$("#sim-controls [data-sim]").forEach((button) => {
      button.addEventListener("click", () => runAction(button.dataset.sim));
    });
    refreshNodePicker();
  }

  window.Simulation = { init, refreshNodePicker, refreshAllViews };
})();
