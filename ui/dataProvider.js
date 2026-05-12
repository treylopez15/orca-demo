/**
 * ORCA UI data access — all network I/O for the dashboard goes through here.
 * When DEMO_MODE is set on the server, endpoints return synthetic payloads (no Slack).
 */
(function (global) {
  const origin = () =>
    typeof global.location !== "undefined" && global.location.origin ? global.location.origin : "";

  let configPromise = null;
  let analyticsBundle = null;

  function jsonDetail(obj) {
    return (obj && obj.detail) || "";
  }

  async function getBootstrapConfig() {
    if (!configPromise) {
      configPromise = fetch(`${origin()}/api/config`, { credentials: "same-origin" })
        .then((r) => r.json())
        .catch(() => ({ demoMode: false }));
    }
    return configPromise;
  }

  async function isDemoMode() {
    const c = await getBootstrapConfig();
    return Boolean(c.demoMode);
  }

  async function getAnalytics(signal) {
    const r = await fetch(`${origin()}/api/analytics/summary`, {
      signal,
      credentials: "same-origin",
    });
    const body = await r.json().catch(() => ({}));
    if (r.status === 404) {
      throw new Error(
        "API not found (404). Restart the server from the project folder so routes reload, " +
          "and open this page at the server /ui/ URL (not as a file:// link)."
      );
    }
    if (!r.ok) throw new Error(jsonDetail(body) || `HTTP ${r.status}`);
    analyticsBundle = body;
    return body;
  }

  async function getInsights(signal) {
    const r = await fetch(`${origin()}/api/insights/summary`, {
      signal,
      credentials: "same-origin",
    });
    if (!r.ok) return null;
    const body = await r.json().catch(() => null);
    return body;
  }

  /** Analytics message rows (same shape as server analyticsMessages). */
  function getMessages() {
    const bundle = analyticsBundle;
    if (!bundle) return [];
    let raw = bundle.analyticsMessages ?? bundle.analytics_messages;
    if (typeof raw === "string") {
      try {
        raw = JSON.parse(raw);
      } catch {
        raw = null;
      }
    }
    return Array.isArray(raw) ? raw : [];
  }

  /** API traffic rows (channel_id, timestamp, endpoint). */
  function getApiTraffic() {
    const bundle = analyticsBundle;
    if (!bundle) return [];
    let raw =
      bundle.apiTrafficActivity ?? bundle.api_traffic_activity ?? bundle.apiActivity ?? null;
    if (typeof raw === "string") {
      try {
        raw = JSON.parse(raw);
      } catch {
        raw = null;
      }
    }
    return Array.isArray(raw) ? raw : [];
  }

  async function getCompanies() {
    const r = await fetch(`${origin()}/api/companies`, { credentials: "same-origin" });
    if (!r.ok) return [];
    const d = await r.json().catch(() => ({}));
    return Array.isArray(d.companies) ? d.companies : [];
  }

  async function getRolesStatus() {
    const r = await fetch(`${origin()}/api/roles/status`, { credentials: "same-origin" });
    if (!r.ok) return null;
    return r.json().catch(() => null);
  }

  async function getBroadcastChannels() {
    const r = await fetch(`${origin()}/api/broadcast/channels`, { credentials: "same-origin" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(jsonDetail(err) || `HTTP ${r.status}`);
    }
    return r.json();
  }

  async function getBroadcastPreflight() {
    const r = await fetch(`${origin()}/api/broadcast/preflight`, { credentials: "same-origin" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(jsonDetail(err) || `HTTP ${r.status}`);
    }
    return r.json();
  }

  async function postBroadcastSend(payload) {
    const r = await fetch(`${origin()}/api/broadcast/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(jsonDetail(body) || `HTTP ${r.status}`);
    return body;
  }

  async function postIngest() {
    const r = await fetch(`${origin()}/ingest`, { method: "POST", credentials: "same-origin" });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(jsonDetail(body) || `HTTP ${r.status}`);
    return body;
  }

  async function postAsk(question) {
    const r = await fetch(`${origin()}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      credentials: "same-origin",
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(jsonDetail(body) || `HTTP ${r.status}`);
    return body;
  }

  global.OrcaDataProvider = {
    getBootstrapConfig,
    isDemoMode,
    getAnalytics,
    getInsights,
    getMessages,
    getApiTraffic,
    getCompanies,
    getRolesStatus,
    getBroadcastChannels,
    getBroadcastPreflight,
    postBroadcastSend,
    postIngest,
    postAsk,
  };
})(typeof window !== "undefined" ? window : globalThis);
