/* Integrity center: SHA-256 expected vs actual per replica. */
(() => {
  "use strict";

  const { $, escapeHtml, toast } = window.UI;

  async function refresh() {
    const tbody = $("#integrity-tbody");
    if (!tbody) return;
    try {
      const report = await window.VaultAPI.integrityReport();
      tbody.innerHTML = report.replicas.map((replica) => {
        const verified = replica.verified;
        return `<tr>
          <td class="mono">${replica.object_id.slice(0, 12)}…</td>
          <td class="mono">${replica.replica_id.slice(-16)}</td>
          <td class="mono">${escapeHtml(replica.node_id)}</td>
          <td class="mono" title="${replica.expected_checksum || ""}">${(replica.expected_checksum || "—").slice(0, 16)}…</td>
          <td class="mono" title="${replica.actual_checksum || ""}">${(replica.actual_checksum || "—").slice(0, 16)}…</td>
          <td>${verified
            ? `<span class="chip chip-ok">✓ VERIFIED</span>`
            : `<span class="chip chip-bad">⚠ CHECKSUM MISMATCH</span>`}</td>
        </tr>`;
      }).join("") || `<tr><td colspan="6" class="empty">No replicas to verify.</td></tr>`;
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty">Integrity report unavailable: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  async function runScan() {
    toast("Running full integrity scan…");
    try {
      const result = await window.VaultAPI.integrityScan();
      toast(`Scan complete: ${result.verified}/${result.replicas_checked} verified` +
        (result.corrupted ? ` · ${result.corrupted} corrupted → repairs scheduled` : ""),
        result.corrupted ? "err" : "ok");
      await Promise.all([refresh(), window.Dashboard.refresh(), window.Repairs.refresh()]);
    } catch (err) {
      toast(err.message, "err");
    }
  }

  window.Integrity = { refresh, runScan };
})();
