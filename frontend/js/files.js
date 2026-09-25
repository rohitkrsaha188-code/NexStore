/* Object explorer + drag-and-drop upload with progress stages. */
(() => {
  "use strict";

  const { $, $$, fmtBytes, chip, escapeHtml, fmtDateTime, toast, shortId } = window.UI;
  let filter = "";

  async function refresh() {
    const tbody = $("#files-tbody");
    if (!tbody) return;
    try {
      const files = await window.VaultAPI.getFiles();
      const visible = files.filter((file) =>
        !filter || file.filename.toLowerCase().includes(filter) || file.object_id.includes(filter)
      );
      tbody.innerHTML = visible.map((file) => {
        const replicaOk = file.healthy_replicas >= file.required_replicas;
        return `<tr>
          <td><strong>${escapeHtml(file.filename)}</strong></td>
          <td class="mono" title="${file.object_id}">${shortId(file.object_id)}</td>
          <td class="mono">${fmtBytes(file.size)}</td>
          <td class="mono">v${file.version}</td>
          <td>
            <span class="${replicaOk ? "" : "stat-value warn"}" style="font-size:.8rem">
              ${file.healthy_replicas}/${file.required_replicas}
            </span>
          </td>
          <td>${chip(replicaOk ? "VERIFIED" : "MISMATCH")}</td>
          <td>${chip(file.status)}</td>
          <td class="mono" title="${file.updated_at}">${fmtDateTime(file.updated_at)}</td>
          <td><div class="actions-cell">
            <a class="btn btn-sm" href="${window.VaultAPI.fileDownloadUrl(file.object_id)}"
               download="${escapeHtml(file.filename)}">Download</a>
            <button class="btn btn-sm" data-act="verify" data-id="${file.object_id}">Verify</button>
            <button class="btn btn-sm" data-act="replicas" data-id="${file.object_id}">Replicas</button>
            <button class="btn btn-sm btn-danger" data-act="delete" data-id="${file.object_id}"
                    data-name="${escapeHtml(file.filename)}">Delete</button>
          </div></td>
        </tr>`;
      }).join("") || `<tr><td colspan="8"><div class="empty"><span class="big">📦</span>
        <strong>No objects yet</strong><span>Upload your first object to start using NexStore.</span>
        <button class="btn btn-primary" onclick=\"document.getElementById('upload-dialog').showModal()\">+ Upload Object</button></div></td></tr>`;

      $$("button[data-act]", tbody).forEach((button) => {
        button.addEventListener("click", () => handleAction(button.dataset));
      });
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="8"><div class="empty"><span class="big">⚠️</span>
        Unable to load objects: ${escapeHtml(err.message)} — check that the backend is running.</div></td></tr>`;
    }
  }

  async function handleAction({ act, id, name }) {
    try {
      if (act === "verify") {
        const result = await window.VaultAPI.verifyFile(id);
        toast(`Verify: ${result.verified}/${result.replicas_checked} replicas verified` +
          (result.corrupted ? ` · ${result.corrupted} corrupted → repair scheduled` : ""), 
          result.corrupted ? "err" : "ok");
      } else if (act === "delete") {
        if (!confirm(`Delete "${name}" and all its replicas?`)) return;
        const result = await window.VaultAPI.deleteFile(id);
        toast(`Deleted ${result.filename} (${result.deleted_replicas} replicas removed)`, "ok");
      } else if (act === "replicas") {
        showReplicaDialog(id);
        return;
      }
      await Promise.all([refresh(), window.Dashboard.refresh()]);
    } catch (err) {
      toast(err.message, "err");
    }
  }

  async function showReplicaDialog(objectId) {
    const dialog = $("#node-dialog");
    const body = $("#node-dialog-body");
    try {
      const detail = await window.VaultAPI.getFile(objectId);
      body.innerHTML = `
        <h3 class="dialog-title">${escapeHtml(detail.filename)} · ${chip(detail.status)}</h3>
        <div class="kv-grid">
          <span class="k">Checksum (SHA-256)</span><span class="v">${detail.checksum.slice(0, 24)}…</span>
          <span class="k">Required replicas</span><span class="v">${detail.required_replicas}</span>
          <span class="k">Healthy replicas</span><span class="v">${detail.healthy_replicas}</span>
        </div>
        <div class="repl-tree" style="margin-top:1rem">
          ${detail.replicas.map((replica) => `
            <div class="repl-branch">
              <span class="node">${replica.node_name || replica.node_id}</span>
              <span>${chip(replica.status)}</span>
              <span>v${replica.version}</span>
              <span>${fmtBytes(replica.size)}</span>
            </div>`).join("")}
        </div>`;
      dialog.showModal();
    } catch (err) {
      toast(err.message, "err");
    }
  }

  /* ============ Upload ============ */
  let selectedFile = null;

  function initUpload() {
    const dialog = $("#upload-dialog");
    const dropZone = $("#drop-zone");
    const input = $("#upload-input");

    $("#btn-upload").addEventListener("click", () => dialog.showModal());
    dropZone.addEventListener("click", () => input.click());
    dropZone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
    });
    input.addEventListener("change", () => setFile(input.files[0]));

    ["dragover", "dragenter"].forEach((eventName) =>
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
      })
    );
    ["dragleave", "drop"].forEach((eventName) =>
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
      })
    );
    dropZone.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));

    $("#upload-form").addEventListener("submit", submitUpload);
    $$("[data-close]").forEach((button) =>
      button.addEventListener("click", () => button.closest("dialog")?.close())
    );
  }

  function setFile(file) {
    if (!file) return;
    selectedFile = file;
    $("#upload-file-name").textContent = `${file.name} · ${fmtBytes(file.size)}`;
  }

  async function submitUpload(event) {
    event.preventDefault();
    if (!selectedFile) {
      toast("Choose a file first", "err");
      return;
    }
    const rf = Number($("#upload-rf").value) || 3;
    const bars = ["#up-bar-1", "#up-bar-2", "#up-bar-3", "#up-bar-4"].map((sel) => $(sel));
    const progress = $("#upload-progress");
    const result = $("#upload-result");
    progress.hidden = false;
    result.textContent = "";
    $("#upload-submit").disabled = true;

    try {
      const response = await window.VaultAPI.uploadFile(selectedFile, rf, (stage, pct) => {
        const index = { uploading: 0, hashing: 1, replicating: 2, verifying: 3 }[stage] ?? 3;
        bars.forEach((bar, i) => {
          bar.style.width = i < index ? "100%" : i === index ? `${pct}%` : "0%";
          bar.parentElement.parentElement.classList.toggle("done", i <= index && pct === 100);
        });
      });
      result.className = "sim-result ok";
      result.textContent =
        `✓ Stored on: ${response.placement.nodes.join(", ")}\n` +
        `SHA-256 ${response.checksum.slice(0, 20)}… · RF=${response.replication_factor}`;
      toast(`Uploaded ${response.filename}`, "ok");
      selectedFile = null;
      $("#upload-file-name").textContent = "No file selected";
      await Promise.all([refresh(), window.Dashboard.refresh(), window.Topology.refresh()]);
    } catch (err) {
      result.className = "sim-result err";
      result.textContent = `✗ ${err.message}`;
      toast(err.message, "err");
    } finally {
      $("#upload-submit").disabled = false;
    }
  }

  function setFilter(value) {
    filter = (value || "").toLowerCase();
  }

  window.Files = { refresh, initUpload, setFilter };
})();
