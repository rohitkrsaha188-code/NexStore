/* Node details slide-over: node stats, stored objects, Add File To Node. */
(() => {
  "use strict";

  const { $, fmtBytes, fmtDateTime, escapeHtml, toast, chip, shortId } = window.UI;
  let targetNode = null;
  let addFile = null;

  async function open(nodeId) {
    targetNode = nodeId;
    const wrap = $("#node-slideover");
    wrap.classList.add("open");
    const body = $("#slideover-body");
    $("#slideover-title").textContent = "Loading…";
    body.innerHTML = `<div class="skeleton" style="height:1rem;width:60%"></div>
                      <div class="skeleton" style="height:8rem;margin-top:1rem"></div>`;
    try {
      const data = await window.VaultAPI.getNodeObjects(nodeId);
      render(data);
    } catch (err) {
      $("#slideover-title").textContent = nodeId;
      body.innerHTML = `<div class="empty"><span class="big">⚠️</span>
        Unable to load node: ${escapeHtml(err.message)}</div>`;
    }
  }

  function render({ node, available, objects }) {
    $("#slideover-title").innerHTML = `${escapeHtml(node.name)} ${chip(node.status)}`;
    const stateClass = node.status === "FAILED" ? "bad" : node.status === "PARTITIONED" ? "warn" : "ok";
    $("#slideover-body").innerHTML = `
      <div class="kv-grid">
        <span class="k">Status</span><span class="v">${escapeHtml(node.status)} · ${escapeHtml(node.network_status)}</span>
        <span class="k">Health</span><span class="v">${escapeHtml(node.health_status)}</span>
        <span class="k">Capacity</span><span class="v">${fmtBytes(node.capacity)}</span>
        <span class="k">Used</span><span class="v">${fmtBytes(node.used_capacity)} (${node.utilization?.toFixed(1) ?? 0}%)</span>
        <span class="k">Available</span><span class="v">${fmtBytes(available)}</span>
        <span class="k">Objects</span><span class="v">${node.object_count}</span>
        <span class="k">Replicas</span><span class="v">${node.replica_count}</span>
        <span class="k">Heartbeat</span><span class="v">${fmtDateTime(node.last_heartbeat)}</span>
      </div>
      <div style="margin:1.1rem 0 0.6rem;display:flex;justify-content:space-between;align-items:center">
        <strong style="font-size:.8rem;letter-spacing:.08em;color:var(--muted)">STORED OBJECTS (${objects.length})</strong>
        <button class="btn btn-primary btn-sm" id="btn-addfile" ${node.status !== "ONLINE" ? "disabled title='Node is not ONLINE'" : ""}>+ Add File To Node</button>
      </div>
      <div class="table-wrap">
        <table class="table" style="min-width:480px">
          <thead><tr><th>Object</th><th>Size</th><th>Checksum</th><th>v</th><th>Replica Status</th><th>Created</th><th>Actions</th></tr></thead>
          <tbody id="node-objects-tbody">
            ${objects.map((row) => `
              <tr>
                <td><strong>${escapeHtml(row.filename)}</strong><br>
                    <span class="mono" style="font-size:.68rem;color:var(--muted)" title="${row.object_id}">${shortId(row.object_id)}</span></td>
                <td class="mono">${fmtBytes(row.size)}</td>
                <td class="mono" title="${row.checksum}">${row.checksum.slice(0, 10)}…</td>
                <td class="mono">v${row.version}</td>
                <td>${chip(row.replica_status)}</td>
                <td class="mono" style="font-size:.72rem">${fmtDateTime(row.created_at)}</td>
                <td><div class="actions-cell">
                  <a class="btn btn-sm" href="/api/files/${row.object_id}/download" download="${escapeHtml(row.filename)}">Download</a>
                  <button class="btn btn-sm" data-verify="${row.object_id}">Verify</button>
                  <button class="btn btn-sm btn-danger" data-del="${row.object_id}" data-name="${escapeHtml(row.filename)}">Delete</button>
                </div></td>
              </tr>`).join("")
            || `<tr><td colspan="7"><div class="empty"><span class="big">📂</span>
                 This storage node currently contains no objects.<br>
                 ${node.status === "ONLINE"
                   ? `<button class="btn btn-primary" id="btn-addfile-empty">+ Add File To Node</button>`
                   : "Restore the node to add files."}</div></td></tr>`}
          </tbody>
        </table>
      </div>
      <div class="sidebar-status ${stateClass}" style="margin-top:1rem">
        <span class="shield">${stateClass === "ok" ? "🛡️" : stateClass === "warn" ? "⚠️" : "⛔"}</span>
        <div><div class="t">${escapeHtml(node.status)}</div>
        <div class="s">Last activity ${fmtDateTime(node.updated_at)}</div></div>
      </div>`;

    const openAdd = $("#btn-addfile") || $("#btn-addfile-empty");
    openAdd?.addEventListener("click", () => openAddFileDialog(node));

    $("#slideover-body").querySelectorAll("[data-verify]").forEach((button) =>
      button.addEventListener("click", async () => {
        try {
          const r = await window.VaultAPI.verifyFile(button.dataset.verify);
          toast(`Verify: ${r.verified}/${r.replicas_checked} replicas verified`, r.corrupted ? "err" : "ok");
        } catch (err) { toast(err.message, "err"); }
      }));
    $("#slideover-body").querySelectorAll("[data-del]").forEach((button) =>
      button.addEventListener("click", async () => {
        if (!confirm(`Delete "${button.dataset.name}" and all its replicas?`)) return;
        try {
          const r = await window.VaultAPI.deleteFile(button.dataset.del);
          toast(`Deleted ${r.filename} (${r.deleted_replicas} replicas removed)`, "ok");
          await open(targetNode);
          window.app.refreshAll();
        } catch (err) { toast(err.message, "err"); }
      }));
  }

  /* ============ Add File To Node modal ============ */
  function openAddFileDialog(node) {
    targetNode = node.node_id;
    $("#addfile-node-name").textContent = node.name;
    $("#addfile-file-name").textContent = "No file selected";
    $("#addfile-result").textContent = "";
    $("#addfile-progress").hidden = true;
    $("#af-bar-1").style.width = "0%";
    $("#addfile-dialog").showModal();
  }

  function init() {
    const dialog = $("#addfile-dialog");
    const drop = $("#addfile-drop");
    const input = $("#addfile-input");

    drop.addEventListener("click", () => input.click());
    drop.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
    });
    input.addEventListener("change", () => setFile(input.files[0]));
    ["dragover", "dragenter"].forEach((name) =>
      drop.addEventListener(name, (e) => { e.preventDefault(); drop.classList.add("dragover"); }));
    ["dragleave", "drop"].forEach((name) =>
      drop.addEventListener(name, (e) => { e.preventDefault(); drop.classList.remove("dragover"); }));
    drop.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));

    $("#addfile-form").addEventListener("submit", submit);

    document.querySelectorAll("[data-close-slideover]").forEach((el) =>
      el.addEventListener("click", () => $("#node-slideover").classList.remove("open")));
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") $("#node-slideover").classList.remove("open");
    });
  }

  function setFile(file) {
    if (!file) return;
    addFile = file;
    $("#addfile-file-name").textContent = `${file.name} · ${fmtBytes(file.size)}`;
  }

  async function submit(event) {
    event.preventDefault();
    if (!addFile) { toast("Choose a file first", "err"); return; }
    const bar = $("#af-bar-1");
    const result = $("#addfile-result");
    $("#addfile-progress").hidden = false;
    result.textContent = "⏳ Uploading to " + targetNode + "…";
    $("#addfile-submit").disabled = true;
    try {
      const response = await window.VaultAPI.uploadToNode(addFile, targetNode, null, (_stage, pct) => {
        bar.style.width = `${pct}%`;
      });
      result.className = "sim-result ok";
      result.textContent = `✓ Uploaded — replica on ${targetNode}, full placement: ${response.placement.nodes.join(", ")}\nSHA-256 ${response.checksum.slice(0, 20)}…`;
      toast(`Uploaded ${response.filename} to ${targetNode}`, "ok");
      addFile = null;
      $("#addfile-file-name").textContent = "No file selected";
      setTimeout(() => { $("#addfile-dialog").close(); }, 900);
      await open(targetNode);
      window.app.refreshAll();
    } catch (err) {
      result.className = "sim-result err";
      result.textContent = `✗ ${err.message}`;
      toast(err.message, "err");
    } finally {
      $("#addfile-submit").disabled = false;
    }
  }

  window.NodeDetail = { open, init };
})();
