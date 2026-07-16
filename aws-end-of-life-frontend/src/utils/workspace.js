// ── Workspace token session ───────────────────────────────────────────────────
// Workspace ID, name, and TOKEN are stored in localStorage.
// Token is permanent (no server-side expiry). A 24-hour client-side session
// window is enforced: after 24h the browser session is cleared and the user
// must re-enter their token. The same token is valid again after re-login.

const ID_KEY           = "eolm_ws_id";
const TOKEN_KEY        = "eolm_ws_token";
const NAME_KEY         = "eolm_ws_name";
const EXPIRES_KEY      = "eolm_ws_expires_at";
const WS_SESSION_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours in milliseconds

export const DEMO_WS_ID = "ws_demo";

// ── Member session ────────────────────────────────────────────────────────────
// All in sessionStorage — cleared when tab closes.
// Member token is a credential — never in localStorage.

const MS_TOKEN_KEY   = "eolm_ms_token";
const MS_ROLE_KEY    = "eolm_ms_role";
const MS_ID_KEY      = "eolm_ms_member_id";
const MS_NAME_KEY    = "eolm_ms_member_name";
const MS_WS_ID_KEY   = "eolm_ms_ws_id";
const MS_WS_NAME_KEY = "eolm_ms_ws_name";
const MS_EXPIRES_KEY = "eolm_ms_expires_at";

export function hasMemberSession() {
  const token = sessionStorage.getItem(MS_TOKEN_KEY);
  const wsId  = sessionStorage.getItem(MS_WS_ID_KEY);
  if (!token || !wsId) return false;
  const expires = Number(sessionStorage.getItem(MS_EXPIRES_KEY) || 0);
  if (expires && Date.now() > expires) {
    clearMemberSession();
    return false;
  }
  return true;
}

export function getMemberSessionToken()  { return sessionStorage.getItem(MS_TOKEN_KEY)   || ""; }
export function getMemberRole()          { return sessionStorage.getItem(MS_ROLE_KEY)     || ""; }
export function getMemberId()            { return sessionStorage.getItem(MS_ID_KEY)       || ""; }
export function getMemberDisplayName()   { return sessionStorage.getItem(MS_NAME_KEY)     || ""; }

export function setMemberSession(workspaceId, workspaceName, token, role, memberId, memberName, expiresAt) {
  sessionStorage.setItem(MS_TOKEN_KEY,   token);
  sessionStorage.setItem(MS_ROLE_KEY,    role);
  sessionStorage.setItem(MS_ID_KEY,      memberId);
  sessionStorage.setItem(MS_NAME_KEY,    memberName || "");
  sessionStorage.setItem(MS_WS_ID_KEY,   workspaceId);
  sessionStorage.setItem(MS_WS_NAME_KEY, workspaceName || "");
  if (expiresAt) {
    sessionStorage.setItem(MS_EXPIRES_KEY, String(new Date(expiresAt).getTime()));
  }
}

export function clearMemberSession() {
  [MS_TOKEN_KEY, MS_ROLE_KEY, MS_ID_KEY, MS_NAME_KEY,
   MS_WS_ID_KEY, MS_WS_NAME_KEY, MS_EXPIRES_KEY].forEach(k =>
    sessionStorage.removeItem(k));
}

// ── Unified workspace accessors ───────────────────────────────────────────────
// Member session workspace takes priority over localStorage workspace token session.

export function getWorkspaceId() {
  return sessionStorage.getItem(MS_WS_ID_KEY) || localStorage.getItem(ID_KEY) || "";
}

export function getWorkspaceToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function getWorkspaceName() {
  return sessionStorage.getItem(MS_WS_NAME_KEY) || localStorage.getItem(NAME_KEY) || "My Workspace";
}

export function setWorkspace(id, token, name) {
  localStorage.setItem(ID_KEY,      id);
  localStorage.setItem(TOKEN_KEY,   token);
  if (name) localStorage.setItem(NAME_KEY, name);
  localStorage.setItem(EXPIRES_KEY, String(Date.now() + WS_SESSION_TTL_MS));
}

// Returns the workspace session expiry timestamp in ms, or 0 if not set.
export function getWorkspaceExpiresAt() {
  return Number(localStorage.getItem(EXPIRES_KEY) || 0);
}

// Pure expiry check — does NOT clear storage. Call this BEFORE clearWorkspace()
// if you need to distinguish "expired" from "never logged in" so the UI can
// show "Session expired. Please login again." vs a blank login panel.
export function isWorkspaceExpired() {
  const id    = localStorage.getItem(ID_KEY);
  const token = localStorage.getItem(TOKEN_KEY);
  if (!id || !token) return false; // absent ≠ expired
  const exp = Number(localStorage.getItem(EXPIRES_KEY) || 0);
  return exp > 0 && Date.now() > exp;
}

export function clearWorkspace() {
  // Capture workspace ID before removing it so we can clear scoped caches.
  const wsId = localStorage.getItem(ID_KEY) || "";
  clearMemberSession();
  localStorage.removeItem(ID_KEY);
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(NAME_KEY);
  localStorage.removeItem(EXPIRES_KEY);
  // Clear workspace-scoped localStorage caches so they do not flash on the
  // next workspace login (different workspace or re-login after rotation).
  if (wsId) {
    localStorage.removeItem(`eolm_connected_accounts:${wsId}`);
  }
}

export function hasWorkspace() {
  if (hasMemberSession()) return true;
  const id    = localStorage.getItem(ID_KEY);
  const token = localStorage.getItem(TOKEN_KEY);
  if (!id || !token) return false;
  const exp = Number(localStorage.getItem(EXPIRES_KEY) || 0);
  // exp === 0 means legacy session (set before this feature) — treat as valid.
  return exp === 0 || Date.now() <= exp;
}

// Returns true if the workspace browser session has expired.
// Delegates to isWorkspaceExpired(); member sessions use their own expiry check.
export function isExpired() {
  if (hasMemberSession()) return false;
  return isWorkspaceExpired();
}

// Returns the active session expiry timestamp (ms) for display purposes.
// Workspace owner: returns workspace expiresAt. Member: returns member session expiresAt.
export function getSessionExpiry() {
  if (hasMemberSession()) {
    return Number(sessionStorage.getItem(MS_EXPIRES_KEY) || 0);
  }
  return getWorkspaceExpiresAt();
}

export function workspaceHeaders() {
  const memberToken = getMemberSessionToken();
  if (memberToken) return { "X-Member-Session-Token": memberToken };
  const token = getWorkspaceToken();
  return token ? { "X-Workspace-Token": token } : {};
}

export function isDemoWorkspace() {
  return getWorkspaceId() === DEMO_WS_ID;
}

export function setDemoWorkspace() {
  localStorage.setItem(ID_KEY,    DEMO_WS_ID);
  localStorage.setItem(TOKEN_KEY, "demo_readonly_sample_data");
  localStorage.setItem(NAME_KEY,  "Demo Workspace");
}
