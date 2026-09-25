/* Replication view: per-object replica map. */
(() => {
  "use strict";

  const { $, chip, escapeHtml } = window.UI;

  async function refresh() {
    const el = $("#replication-map");
    if (!el) return;
    try {
      const [files, settings] = await Promise.all([
        window.VaultAPI.getFiles(),
        window.VaultAPI.getSettings(),
      ]);
      $("#rf-hint").textContent = `cluster replication factor: ${settings.replication_factor}×`;
      el.innerHTML = files.map((file) => {
        const missing = Math.max(0, file.required_replicas - file.healthy_replicas);
        return `<div class="repl-object">
          <div class="repl-head">
            <div class="repl-name">${escapeHtml(file.filename)}
              <span class="oid">${shortOid(file.object_id)}</span>
            </div>
            <div class="repl-meta">
              <span class="chip ${missing ? "chip-warn" : "chip-ok"}">
                ${file.healthy_replicas}/${file.required_replicas} replicas
              </span>
              ${missing ? `<span class="chip chip-bad">${missing} missing</span>` : ""}
              <span class="chip chip-muted">RF ${file.replication_factor}</span>
              ${chip(file.status)}
            </div>
          </div>
          <div class="repl-tree" data-object="${file.object_id}">
            <span class="repl-branch"><strong>OBJECT</strong></span>
            <span id="repl-branches-${file.object_id}" style="display:contents"></span>
          </div>
        </div>`;
      }).join("") || `<div class="empty"><span class="big">🗂️</span>No objects yet.
        <button class="btn btn-primary" onclick="document.getElementById('upload-dialog').showModal()">+ Upload Object</button>
        <span>Upload your first object to see its replica map.</span></div>`;

      for (const file of files) {
        const detail = await window.VaultAPI.getFile(file.object_id);
        const holder = $(`#repl-branches-${file.object_id}`);
        if (!holder) continue;
        holder.innerHTML = detail.replicas.map((replica) => `
          <span class="repl-branch">
            <span class="node">${replica.node_name || replica.node_id}</span>
            ${chip(replica.status)}
            <span>v${replica.version}</span>
          </span>`).join("");
      }
    } catch (err) {
      el.innerHTML = `<div class="empty">Replication map unavailable: ${escapeHtml(err.message)}</div>`;
    }
  }

  function shortOid(id) {
    return id ? `${id.slice(0, 10)}…` : "";
  }

  window.Replication = { refresh };
})();
