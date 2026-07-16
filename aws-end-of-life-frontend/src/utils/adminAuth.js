const TOKEN_KEY   = "eolm_admin_token";
const EXPIRES_KEY = "eolm_admin_expires_at";
const SESSION_MS  = 60 * 60 * 1000; // 1 hour

export function setAdminSession(token) {
  sessionStorage.setItem(TOKEN_KEY,   token);
  sessionStorage.setItem(EXPIRES_KEY, String(Date.now() + SESSION_MS));
}

export function getAdminToken() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

export function clearAdminSession() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(EXPIRES_KEY);
}

export function hasAdminSession() {
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (!token) return false;
  const expires = Number(sessionStorage.getItem(EXPIRES_KEY) || 0);
  if (expires && Date.now() > expires) {
    clearAdminSession();
    return false;
  }
  return true;
}

export function getAdminSessionExpiry() {
  return Number(sessionStorage.getItem(EXPIRES_KEY) || 0);
}
