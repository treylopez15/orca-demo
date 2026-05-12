/**
 * Display-only channel name aliases for public demos (does not change API payloads).
 * Set window.__ORCA_DEMO_MODE__ from /api/config when demoMode is true.
 */
(function (global) {
  const RAW_TO_MASK = new Map([
    ["makeba-support", "client-a-support"],
    ["nuvion-braid", "client-b-support"],
  ]);

  function maskChannelDisplayName(raw) {
    if (!global.__ORCA_DEMO_MODE__) return String(raw || "");
    const s = String(raw || "");
    const stripped = s.replace(/^#/, "").trim();
    const key = stripped.toLowerCase();
    if (!RAW_TO_MASK.has(key)) return s;
    const mapped = RAW_TO_MASK.get(key);
    return s.trim().startsWith("#") ? `#${mapped}` : mapped;
  }

  global.OrcaChannelMask = { maskChannelDisplayName };
})(typeof window !== "undefined" ? window : globalThis);
