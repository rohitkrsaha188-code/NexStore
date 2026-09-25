/* Settings form: load, validate, save cluster configuration. */
(() => {
  "use strict";

  const { $, toast } = window.UI;

  async function refresh() {
    try {
      const settings = await window.VaultAPI.getSettings();
      $("#set-rf").value = settings.replication_factor;
      $("#set-health").value = settings.health_check_interval;
      $("#set-repair").value = settings.repair_interval;
      $("#set-integrity").value = settings.integrity_check_interval;
      $("#set-threshold").value = settings.rebalance_threshold;
      $("#set-capacity").value = settings.max_storage_per_node;
      const nodes = await window.VaultAPI.getNodes();
      $("#set-rf-hint").textContent =
        `must be between 1 and the number of healthy nodes (${nodes.filter((n) => n.status === "ONLINE").length})`;
    } catch (err) {
      toast(`Could not load settings: ${err.message}`, "err");
    }
  }

  async function save(event) {
    event.preventDefault();
    const status = $("#settings-status");
    const patch = {
      replication_factor: Number($("#set-rf").value),
      health_check_interval: Number($("#set-health").value),
      repair_interval: Number($("#set-repair").value),
      integrity_check_interval: Number($("#set-integrity").value),
      rebalance_threshold: Number($("#set-threshold").value),
      max_storage_per_node: Number($("#set-capacity").value),
    };
    try {
      await window.VaultAPI.updateSettings(patch);
      status.textContent = "✓ saved";
      status.style.color = "var(--ok)";
      toast("Settings saved", "ok");
      window.Dashboard.refresh();
    } catch (err) {
      status.textContent = `✗ ${err.message}`;
      status.style.color = "var(--danger)";
      toast(err.message, "err");
    }
  }

  function init() {
    $("#settings-form").addEventListener("submit", save);
    refresh();
  }

  window.Settings = { init, refresh };
})();
