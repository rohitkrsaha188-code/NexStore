/* Topology visualization: router → nodes with repair flow indicators. */
(() => {
  "use strict";

  const { $ } = window.UI;

  async function refresh() {
    const el = $("#topology");
    if (!el) return;
    try {
      const [nodes, repairs] = await Promise.all([
        window.VaultAPI.getNodes(),
        window.VaultAPI.getRepairs(20),
      ]);
      const active = repairs.filter((r) => ["QUEUED", "RUNNING", "VERIFYING"].includes(r.status));
      const failedIds = new Set(active.map((r) => r.failed_node_id).filter(Boolean));
      const replacementIds = new Set(active.map((r) => r.replacement_node_id).filter(Boolean));

      el.innerHTML = `
        <div class="topo-root">NEXSTORE</div>
        <div class="topo-router">DISTRIBUTED ROUTER</div>
        <div class="topo-trunk"></div>
        <div class="topo-row">
          ${nodes.map((node) => {
            const status = node.status.toLowerCase();
            const isFailedSource = failedIds.has(node.node_id);
            const isRepairTarget = replacementIds.has(node.node_id);
            return `<div class="topo-node" tabindex="0" role="button"
                        data-node="${node.node_id}" aria-label="${node.node_id} ${node.status}">
              ${isRepairTarget ? `<span class="topo-repair">↙ repair target</span>` : ""}
              <div class="topo-box">
                <div class="topo-id">${node.name}</div>
                <span class="topo-status ${status}"></span>
                <div class="topo-meta">${Math.round(node.utilization)}% · ${node.replica_count} repl</div>
              </div>
            </div>`;
          }).join("")}
        </div>`;

      el.querySelectorAll(".topo-node").forEach((item) => {
        item.addEventListener("click", () => window.Nodes.showDialog(item.dataset.node));
        item.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            window.Nodes.showDialog(item.dataset.node);
          }
        });
      });
    } catch {
      el.innerHTML = `<div class="empty">Topology unavailable</div>`;
    }
  }

  window.Topology = { refresh };
})();
