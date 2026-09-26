/* App shell: sidebar routing, page chrome, refresh orchestration, polling. */
(() => {
  "use strict";

  const { $, $$ } = window.UI;

  const PAGES = {
    dashboard:   { title: "Dashboard",   sub: "Overview of your distributed object storage cluster", crumb: "NexStore — Distributed Storage" },
    objects:     { title: "Objects",     sub: "Manage objects stored across the distributed cluster", crumb: "Home / Objects" },
    nodes:       { title: "Storage Nodes", sub: "Fleet health, capacity, and stored objects", crumb: "Home / Storage Nodes" },
    replication: { title: "Replication", sub: "Where every object's replicas live", crumb: "Home / Replication" },
    repairs:     { title: "Repair",      sub: "Automatic recovery jobs and repair history", crumb: "Home / Repair" },
    integrity:   { title: "Integrity",   sub: "SHA-256 verification across all replicas", crumb: "Home / Integrity" },
    rebalancing: { title: "Rebalancing", sub: "Move replicas from hot nodes to cool nodes", crumb: "Home / Rebalancing" },
    activity:    { title: "Activity",    sub: "Everything the cluster has done, newest first", crumb: "Home / Activity" },
    profile:     { title: "Profile",     sub: "Your authenticated account", crumb: "Home / Profile" },
    settings:    { title: "Settings",    sub: "Cluster-wide replication and worker configuration", crumb: "Home / Settings" },
  };

  const VIEW_REFRESH = {
    dashboard: () => Promise.all([
      window.Dashboard.refresh(), window.Topology.refresh(),
      window.Activity.refreshFeed(), window.Simulation.refreshNodePicker(),
    ]),
    objects: () => window.Files.refresh(),
    nodes: () => window.Nodes.refresh(),
    replication: () => window.Replication.refresh(),
    repairs: () => window.Repairs.refresh(),
    integrity: () => window.Integrity.refresh(),
    rebalancing: () => window.Rebalancing.refresh(),
    activity: () => window.Activity.refreshTable(),
    profile: () => Promise.resolve(),
    settings: () => window.Settings.refresh(),
  };

  let currentView = "dashboard";

  function switchView(name) {
    if (!PAGES[name]) return;
    currentView = name;
    $$(".side-link").forEach((link) =>
      link.classList.toggle("active", link.dataset.view === name));
    $$(".view").forEach((view) => {
      const active = view.id === `view-${name}`;
      view.classList.toggle("active", active);
      view.hidden = !active;
    });
    const page = PAGES[name];
    $("#page-title").textContent = page.title;
    $("#page-sub").textContent = page.sub;
    $("#crumb").textContent = page.crumb;
    $("#sidebar")?.classList.remove("open");
    VIEW_REFRESH[name]?.();
  }

  function refreshAll() {
    window.Dashboard.refresh();
    window.Topology.refresh();
    window.Notifications.refresh();
    if (currentView !== "dashboard") VIEW_REFRESH[currentView]?.();
  }

  function initNav() {
    $$(".side-link").forEach((link) =>
      link.addEventListener("click", () => switchView(link.dataset.view)));
  }

  function initActionButtons() {
    $("#btn-run-repairs")?.addEventListener("click", () => window.Repairs.refresh());
    $("#btn-integrity-scan")?.addEventListener("click", () => window.Integrity.runScan());
    $("#btn-rebalance")?.addEventListener("click", () => window.Rebalancing.trigger());
    $("#btn-refresh-activity")?.addEventListener("click", () => window.Activity.refreshTable());
    $("#file-search")?.addEventListener("input", (event) => {
      window.Files.setFilter(event.target.value);
      window.Files.refresh();
    });
    $("#btn-upload")?.addEventListener("click", () => $("#upload-dialog").showModal());
  }

  async function refreshBadge(stats) {
    const badge = $("#cluster-badge");
    const text = $("#cluster-badge-text");
    const health = stats?.system_health || "HEALTHY";
    const synced = stats?.replication_factor
      ? `SYNCED EVERY ${window.Settings?.intervalLabel ?? "2 MIN"}`
      : "SYNCED";
    if (health === "HEALTHY") {
      badge.className = "status-badge";
      text.textContent = `CLUSTER ONLINE • ${stats.nodes_online}/${stats.nodes_total} NODES • ${synced}`;
    } else if (health === "DEGRADED") {
      badge.className = "status-badge warn";
      text.textContent = `CLUSTER DEGRADED • ${stats.nodes_online}/${stats.nodes_total} NODES ONLINE`;
    } else {
      badge.className = "status-badge bad";
      text.textContent = `CLUSTER CRITICAL • ${stats.nodes_online}/${stats.nodes_total} NODES ONLINE`;
    }

    // sidebar system-health card
    const card = $("#sidebar-status");
    const title = $("#ss-title");
    const sub = $("#ss-sub");
    card.classList.remove("ok", "warn", "bad");
    if (health === "HEALTHY") {
      card.classList.add("ok");
      title.textContent = "System Healthy";
      sub.textContent = "All services running";
    } else if (health === "DEGRADED") {
      card.classList.add("warn");
      title.textContent = "System Degraded";
      sub.textContent = `${stats.nodes_failed + stats.nodes_partitioned} node(s) unavailable`;
    } else {
      card.classList.add("bad");
      title.textContent = "System Critical";
      sub.textContent = "Immediate attention required";
    }
  }

  function startPolling() {
    const tick = () => {
      window.Dashboard.refresh();
      window.Notifications.refresh();
      if (currentView === "dashboard") {
        window.Topology.refresh();
        window.Activity.refreshFeed();
      } else if (currentView === "repairs" || currentView === "nodes") {
        VIEW_REFRESH[currentView]?.();
      }
    };
    setInterval(tick, 5000);
  }

  function boot() {
    initNav();
    initActionButtons();
    window.Files.initUpload();
    window.Simulation.init();
    window.Settings.init();
    window.NodeDetail.init();
    window.Palette.init();
    window.Notifications.init();
    window.Auth.init();
    window.Dashboard.refresh();
    window.Topology.refresh();
    window.Activity.refreshFeed();
    switchView("dashboard");
    startPolling();
  }

  document.addEventListener("DOMContentLoaded", boot);

  window.app = { switchView, refreshAll, refreshBadge, get currentView() { return currentView; } };

  // Auth gate runs after DOM ready; render login before booting data refreshes.
  document.addEventListener("DOMContentLoaded", () => window.Auth.boot());
})();
