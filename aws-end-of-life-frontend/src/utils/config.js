/**
 * Central runtime config for AWS EOL Monitor frontend.
 *
 * Three environment variables control behavior:
 *
 *   REACT_APP_API_URL          — backend base URL (required in production)
 *   REACT_APP_ENABLE_DEMO_DATA — "true" enables mock-data fallback (local dev only)
 *   REACT_APP_ENABLE_ORG_SCAN — "true" enables Organization Scan (default: off)
 */

// Empty string = relative URLs, which CRA proxy forwards to localhost:3001 in dev
// and which work on the same origin in production.
export const API_BASE_URL = process.env.REACT_APP_API_URL ?? "";

// Demo mode is off unless explicitly set to "true".
export const IS_DEMO_ENABLED = process.env.REACT_APP_ENABLE_DEMO_DATA === "true";

// Runtime check — also true when the user has loaded the demo workspace.
// Called at query time so it reflects the current localStorage state.
export function isDemoEnabled() {
  if (IS_DEMO_ENABLED) return true;
  try { return localStorage.getItem("eolm_ws_id") === "ws_demo"; } catch { return false; }
}

// Feature flags are disabled unless explicitly set to "true".
// REACT_APP_ORG_SCAN_ENABLED is kept for backwards compatibility.
export const ORG_SCAN_ENABLED =
  process.env.REACT_APP_ENABLE_ORG_SCAN === "true" ||
  process.env.REACT_APP_ORG_SCAN_ENABLED === "true";
export const REMEDIATION_ENABLED = process.env.REACT_APP_ENABLE_REMEDIATION === "true";
export const SSO_ENABLED = process.env.REACT_APP_ENABLE_SSO === "true";
export const BILLING_ENABLED = process.env.REACT_APP_ENABLE_BILLING === "true";
export const CICD_SCAN_ENABLED = process.env.REACT_APP_ENABLE_CICD_SCAN === "true";

// Internal admin shortcut stays hidden from normal product navigation unless
// explicitly enabled. The direct /admin route remains available.
export const SHOW_ADMIN_SHORTCUT =
  process.env.REACT_APP_SHOW_ADMIN_SHORTCUT === "true";

if (process.env.NODE_ENV === "development") {
  console.log("[config] API_BASE_URL:", API_BASE_URL || "(empty — relative URLs)");
  console.log("[config] IS_DEMO_ENABLED:", IS_DEMO_ENABLED);
  console.log("[config] ORG_SCAN_ENABLED:", ORG_SCAN_ENABLED);
  console.log("[config] SHOW_ADMIN_SHORTCUT:", SHOW_ADMIN_SHORTCUT);
}

// In dev, CRA proxy is always available even when API_BASE_URL is empty.
// We treat the API as present unless we're in demo-only mode.
export const HAS_API = !IS_DEMO_ENABLED;

// True in a realistic production-like session: API available, demo disabled.
export const IS_PRODUCTION_LIKE = HAS_API && !IS_DEMO_ENABLED;
