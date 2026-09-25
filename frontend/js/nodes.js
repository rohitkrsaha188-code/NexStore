/* Nodes view: cards open the Node Details slide-over. */
(() => {
  "use strict";

  const { $, $$, fmtBytes, chip } = window.UI;

  async function refresh() {
    const grid = $("#node-grid");
    if (!grid) return;
    grid.innerHTML = Array.from({ length: 5 }, () =>
      `<div class="node-card"><div class="skeleton" style="height:1rem;width:50%"></div>
       <div class="skeleton" style="height:5rem;margin-top:.8rem"></div></div>`).join("");
    try {
      const nodes = await window.VaultAPI.getNodes();
      if (!nodes.length) {
        grid.innerHTML = `<div class="panel" style="grid-column:1/-1"><div class="empty">
          <span class="big">🗄️</span>No storage nodes registered.</div></div>`;
        return;
      }
      grid.innerHTML = nodes.map((node) => {
        const util = node.utilization || 0;
        const fill = util > 85 ? "bad" : util > 60 ? "warn" : "";
        return `<article class="node-card ${node.status.toLowerCase()}" tabindex="0" role="button"
                    data-node="${node.node_id}" aria-label="Open ${node.node_id} details">
          <div class="node-head">
            <span class="node-id">${node.name}</span>
            ${chip(node.status)}
          </div>
          <div class="node-body">
            <div class="row"><span>Health</span><span class="v">${chip(node.health_status)}</span></div>
            <div class="row"><span>Storage</span>
              <span class="v">${fmtBytes(node.used_capacity)} / ${fmtBytes(node.capacity)}</span></div>
            <div class="row"><span>Objects</span><span class="v">${node.object_count}</span></div>
            <div class="row"><span>Replicas</span><span class="v">${node.replica_count}</span></div>
            <div class="row"><span>Network</span><span class="v">${chip(node.network_status)}</span></div>
          </div>
          <div class="bar"><div class="bar-fill ${fill}" style="width:${Math.min(util, 100)}%"></div></div>
        </article>`;
      }).join("");

      $$(".node-card", grid).forEach((card) => {
        card.addEventListener("click", () => window.NodeDetail.open(card.dataset.node));
        card.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            window.NodeDetail.open(card.dataset.node);
          }
        });
      });
    } catch {
      grid.innerHTML = `<div class="panel" style="grid-column:1/-1"><div class="empty">
        <span class="big">⚠️</span>Nodes unavailable — is the backend running?</div></div>`;
    }
  }

  window.Nodes = { refresh };
})();
