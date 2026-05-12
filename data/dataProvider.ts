/**
 * Browser-side contract mirroring `ui/dataProvider.js` (ORCA UI is static JS + FastAPI).
 *
 * Runtime helpers that mirror the last loaded analytics bundle (`getMessages`, `getApiTraffic`)
 * live in `ui/dataProvider.js`. This module is a typed reference for integrations or a future TS build.
 */

export type OrcaBootstrapConfig = {
  demoMode: boolean;
};

const origin = (): string =>
  typeof window !== "undefined" && window.location?.origin ? window.location.origin : "";

export async function getBootstrapConfig(): Promise<OrcaBootstrapConfig> {
  const r = await fetch(`${origin()}/api/config`, { credentials: "same-origin" });
  return (await r.json()) as OrcaBootstrapConfig;
}

/** True when server has DEMO_MODE enabled — synthetic data, no Slack side effects. */
export const isDemoMode = async (): Promise<boolean> => {
  const c = await getBootstrapConfig();
  return Boolean(c.demoMode);
};

export async function getAnalytics(signal?: AbortSignal): Promise<Record<string, unknown>> {
  const r = await fetch(`${origin()}/api/analytics/summary`, { signal, credentials: "same-origin" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json() as Promise<Record<string, unknown>>;
}

export async function getInsights(signal?: AbortSignal): Promise<Record<string, unknown> | null> {
  const r = await fetch(`${origin()}/api/insights/summary`, { signal, credentials: "same-origin" });
  if (!r.ok) return null;
  return r.json() as Promise<Record<string, unknown>>;
}

export async function getCompanies(): Promise<unknown[]> {
  const r = await fetch(`${origin()}/api/companies`, { credentials: "same-origin" });
  if (!r.ok) return [];
  const d = (await r.json()) as { companies?: unknown[] };
  return Array.isArray(d.companies) ? d.companies : [];
}

/** Message rows from the last loaded analytics bundle — call after `getAnalytics`. */
export function getMessages(_lastAnalytics: Record<string, unknown> | null): unknown[] {
  void _lastAnalytics;
  return [];
}

export function getApiTraffic(_lastAnalytics: Record<string, unknown> | null): unknown[] {
  void _lastAnalytics;
  return [];
}
