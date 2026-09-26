/* Command palette + global search: Ctrl+K, real /api/search queries. */
(() => {
  "use strict";

  const { $, $$ } = window.UI;
  const dialog = $("#palette");
  const input = $("#palette-input");
  const list = $("#palette-list");
  let items = [];
  let selected = 0;
  let searchSeq = 0;

  const STATIC_COMMANDS = [
    { type: "cmd", title: "Go to Dashboard", view: "dashboard" },
    { type: "cmd", title: "Go to Objects", view: "objects" },
    { type: "cmd", title: "Go to Storage Nodes", view: "nodes" },
    { type: "cmd", title: "Go to Replication", view: "replication" },
    { type: "cmd", title: "Go to Repair", view: "repairs" },
    { type: "cmd", title: "Go to Integrity", view: "integrity" },
    { type: "cmd", title: "Go to Rebalancing", view: "rebalancing" },
    { type: "cmd", title: "Go to Activity", view: "activity" },
    { type: "cmd", title: "Go to Settings", view: "settings" },
    { type: "cmd", title: "Upload Object", run: () => $("#upload-dialog")?.showModal() },
    { type: "cmd", title: "Run Integrity Scan", run: () => window.Integrity.runScan() },
    { type: "cmd", title: "Trigger Rebalance", run: () => window.Rebalancing.trigger() },
  ];

  function open() {
    dialog.showModal();
    input.value = "";
    render(STATIC_COMMANDS);
    input.focus();
  }

  function render(entries) {
    items = entries;
    selected = 0;
    list.innerHTML = entries.length
      ? entries.map((item, i) => `
          <button class="palette-item" data-index="${i}">
            <span class="pi-type">${item.type}</span>
            <span><div class="pi-title">${escapeHtml(item.title)}</div>
            ${item.subtitle ? `<div class="pi-sub">${escapeHtml(item.subtitle)}</div>` : ""}</span>
          </button>`).join("")
      : `<div class="palette-empty">No matches. Try a node id, filename, or command.</div>`;
    list.querySelectorAll(".palette-item").forEach((el) => {
      el.addEventListener("click", () => choose(Number(el.dataset.index)));
      el.addEventListener("mousemove", () => highlight(Number(el.dataset.index)));
    });
    highlight(0);
  }

  function escapeHtml(value) {
    const d = document.createElement("div");
    d.textContent = value == null ? "" : String(value);
    return d.innerHTML;
  }

  function highlight(index) {
    selected = index;
    list.querySelectorAll(".palette-item").forEach((el, i) =>
      el.classList.toggle("selected", i === index));
  }

  function choose(index) {
    const item = items[index];
    if (!item) return;
    dialog.close();
    if (item.view) {
      window.app.switchView(item.view);
      if (item.type === "node" && item.ref) window.NodeDetail.open(item.ref);
      if (item.type === "object" && item.ref) window.app.switchView("objects");
    } else if (item.run) {
      item.run();
    }
  }

  async function search(term) {
    const seq = ++searchSeq;
    const q = term.trim().toLowerCase();
    const commands = STATIC_COMMANDS.filter((c) => !q || c.title.toLowerCase().includes(q));
    if (!q) {
      render(commands.slice(0, 10));
      return;
    }
    let results = [];
    try {
      const data = await window.VaultAPI.search(q);
      if (seq !== searchSeq) return; // stale response
      results = data.results.map((r) => ({
        type: r.type, title: r.title, subtitle: r.subtitle,
        view: r.view, ref: r.ref,
      }));
    } catch { /* fall back to commands only */ }
    render([...results, ...commands].slice(0, 14));
  }

  function init() {
    // Header search launcher (pill button) + any legacy searchbox
    $("#searchbox")?.addEventListener("click", open);
    $("#global-search")?.addEventListener("focus", open);
    input.addEventListener("input", () => search(input.value));
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        highlight(Math.min(selected + 1, items.length - 1));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        highlight(Math.max(selected - 1, 0));
      } else if (event.key === "Enter") {
        event.preventDefault();
        choose(selected);
      }
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        dialog.open ? dialog.close() : open();
      }
    });
  }

  window.Palette = { init, open };
})();
