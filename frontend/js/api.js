/* NexStore API client — the only module that talks to the backend. */
(() => {
  "use strict";

  const BASE = ""; // same-origin; served by FastAPI or a dev proxy

  class ApiError extends Error {
    constructor(status, payload) {
      super((payload && payload.message) || `Request failed (${status})`);
      this.status = status;
      this.error = payload && payload.error;
      this.payload = payload;
    }
  }

  async function request(path, options = {}) {
    let response;
    try {
      response = await fetch(BASE + path, options);
    } catch (networkError) {
      throw new ApiError(0, { message: "Backend unreachable — is the server running?" });
    }
    if (response.status === 204) return null;
    const isJson = (response.headers.get("content-type") || "").includes("application/json");
    const body = isJson ? await response.json().catch(() => null) : null;
    if (!response.ok) throw new ApiError(response.status, body);
    return body;
  }

  const json = (method, body) => ({
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  window.VaultAPI = {
    ApiError,

    // system
    getHealth: () => request("/api/health"),
    getStats: () => request("/api/system/stats"),
    getSettings: () => request("/api/system/settings"),
    updateSettings: (patch) => request("/api/system/settings", json("PUT", patch)),
    getEvents: (limit = 50) => request(`/api/system/events?limit=${limit}`),

    // nodes
    getNodes: () => request("/api/nodes"),
    getNode: (id) => request(`/api/nodes/${id}`),
    getNodeReplicas: (id) => request(`/api/nodes/${id}/replicas`),
    failNode: (id) => request(`/api/nodes/${id}/fail`, { method: "POST" }),
    restoreNode: (id) => request(`/api/nodes/${id}/restore`, { method: "POST" }),
    partitionNode: (id) => request(`/api/nodes/${id}/partition`, { method: "POST" }),
    reconnectNode: (id) => request(`/api/nodes/${id}/reconnect`, { method: "POST" }),

    // files
    getFiles: () => request("/api/files"),
    getFile: (id) => request(`/api/files/${id}`),
    deleteFile: (id) => request(`/api/files/${id}`, { method: "DELETE" }),
    verifyFile: (id) => request(`/api/files/${id}/verify`, { method: "POST" }),
    corruptObjectReplica: (id, nodeId) =>
      request(`/api/files/${id}/corrupt${nodeId ? `?node_id=${nodeId}` : ""}`, { method: "POST" }),
    fileDownloadUrl: (id) => `${BASE}/api/files/${id}/download`,

    uploadFile: async (file, replicationFactor, onStage) => {
      const form = new FormData();
      const pathName = file.relativePath || file.webkitRelativePath || file.name;
      form.append("file", file, pathName);
      const url = `/api/files/upload${replicationFactor ? `?replication_factor=${replicationFactor}` : ""}`;
      onStage && onStage("uploading", 15);
      const body = await request(url, { method: "POST", body: form });
      onStage && onStage("hashing", 45);
      onStage && onStage("replicating", 80);
      onStage && onStage("verifying", 95);
      onStage && onStage("done", 100);
      return body;
    },

    // replicas / consistency
    getReplicas: () => request("/api/replicas"),
    getConsistency: (objectId) => request(`/api/replicas/consistency/${objectId}`),

    // repairs
    getRepairs: (limit = 100) => request(`/api/repairs?limit=${limit}`),
    getRepairMetrics: () => request("/api/repairs/metrics"),
    retryRepair: (id) => request(`/api/repairs/${id}/retry`, { method: "POST" }),

    // integrity
    integrityScan: () => request("/api/integrity/scan", { method: "POST" }),
    integrityReport: () => request("/api/integrity/report"),

    // rebalancing
    triggerRebalance: () => request("/api/rebalance", { method: "POST" }),
    getRebalanceStatus: () => request("/api/rebalance/status"),
    getRebalanceJobs: () => request("/api/rebalance/jobs"),
    getRebalancePlan: () => request("/api/rebalance/plan"),

    // activity
    getActivity: (limit = 100) => request(`/api/activity?limit=${limit}`),

    // search / command palette
    search: (q) => request(`/api/search?q=${encodeURIComponent(q)}`),

    // node detail with stored objects
    getNodeObjects: (id) => request(`/api/nodes/${id}/objects`),

    // Add File To Node (first replica pinned to the node)
    uploadToNode: (file, nodeId, replicationFactor, onStage) => {
      const form = new FormData();
      form.append("file", file, file.name);
      const params = new URLSearchParams({ node_id: nodeId });
      if (replicationFactor) params.set("replication_factor", String(replicationFactor));
      onStage && onStage("uploading", 20);
      return request(`/api/files/upload-to-node?${params}`, { method: "POST", body: form })
        .then((body) => {
          onStage && onStage("done", 100);
          return body;
        });
    },

    // auth
    getMe: () => request("/api/auth/me"),
    devLogin: (email, password) => request("/api/auth/dev-login", json("POST", { email, password })),
    logout: () => request("/api/auth/logout", { method: "POST" }),
    googleLoginUrl: "/auth/google/login",

    // Supabase auth (used when Supabase is configured)
    supabaseLogin: (email, password) => request("/api/auth/login", json("POST", { email, password })),
    supabaseSignup: (email, password, full_name) => request("/api/auth/signup", json("POST", { email, password, full_name })),
    supabaseResetPassword: (email) => request("/api/auth/reset-password", json("POST", { email })),
    supabaseSession: (access_token, refresh_token) =>
      request("/api/auth/supabase-session", json("POST", { access_token, refresh_token })),
    supabaseConfig: () => request("/api/auth/supabase-config"),
    supabaseGoogleLoginUrl: "/auth/supabase/google",
  };
})();
