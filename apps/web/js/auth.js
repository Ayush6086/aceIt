// Production sign-in: Amazon Cognito hosted page, OAuth authorization-code flow with PKCE. The browser holds no secret
// (the Cognito app client has none). The API is called with the ID token; the API checks signature, issuer, audience and type.

// ---- pure helpers (tested in tests/auth.test.mjs)
export const b64url = (bytes) => btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
export const randomString = (n = 48) => b64url(crypto.getRandomValues(new Uint8Array(n)));
export async function pkceChallenge(verifier) { return b64url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)))); }
export function jwtPayload(token) {
  try { return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(token.split(".")[1].replaceAll("-", "+").replaceAll("_", "/")), (c) => c.charCodeAt(0)))); } catch { return null; }
}
export const isExpiring = (expSeconds, nowMs, skewS = 60) => !expSeconds || expSeconds * 1000 - nowMs < skewS * 1000;
const base = (domain) => (/^localhost(:\d+)?$/.test(domain) ? "http://" : "https://") + domain;      // plain http only for a local test sign-in page
export const authorizeUrl = (cfg, redirect, state, challenge) =>
  `${base(cfg.domain)}/oauth2/authorize?` + new URLSearchParams({ response_type: "code", client_id: cfg.client_id, redirect_uri: redirect, scope: "openid email", state, code_challenge: challenge, code_challenge_method: "S256" });
export const logoutUrl = (cfg, redirect) => `${base(cfg.domain)}/logout?` + new URLSearchParams({ client_id: cfg.client_id, logout_uri: redirect });

// ---- storage: tokens in localStorage (so a reload keeps you signed in); the one-time PKCE values in sessionStorage
const TOKENS = "aceit.tokens", PKCE = "aceit.pkce";
const mem = {};
const read = (store, k) => { try { return JSON.parse(store.getItem(k) || "null"); } catch { return mem[k] ?? null; } };
const write = (store, k, v) => { try { v === null ? store.removeItem(k) : store.setItem(k, JSON.stringify(v)); } catch { mem[k] = v; } };
export const tokens = { get: () => read(localStorage, TOKENS) ?? mem[TOKENS] ?? null, set: (t) => write(localStorage, TOKENS, t), clear: () => { write(localStorage, TOKENS, null); delete mem[TOKENS]; } };
export const signedInAs = () => { const t = tokens.get(); const p = t && jwtPayload(t.id); return p ? p.email || p["cognito:username"] || "you" : null; };
const redirectUri = () => location.origin + "/";

// ---- the flow
export async function startLogin(cfg) {
  const verifier = randomString(64), state = randomString(16);
  write(sessionStorage, PKCE, { verifier, state });
  location.assign(authorizeUrl(cfg, redirectUri(), state, await pkceChallenge(verifier)));
}

async function tokenCall(cfg, params) {
  const res = await fetch(`${base(cfg.domain)}/oauth2/token`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ client_id: cfg.client_id, ...params }) });
  if (!res.ok) throw new Error("Sign-in failed");
  return res.json();
}
const keep = (r, old) => { const p = jwtPayload(r.id_token); tokens.set({ id: r.id_token, refresh: r.refresh_token || old?.refresh, exp: p?.exp }); };

/** Called on page load: if Cognito sent the browser back with ?code=..., finish the sign-in. Returns true when it did. */
export async function handleCallback(cfg) {
  const q = new URLSearchParams(location.search);
  if (!q.has("code") && !q.has("error")) return false;
  const saved = read(sessionStorage, PKCE); write(sessionStorage, PKCE, null);
  history.replaceState(null, "", "/#/");                                  // the code is single-use: remove it from the address bar
  if (q.has("error") || !saved || q.get("state") !== saved.state) throw new Error("Sign-in was cancelled or could not be verified. Please try again.");   // state mismatch = possible forged callback
  keep(await tokenCall(cfg, { grant_type: "authorization_code", code: q.get("code"), redirect_uri: redirectUri(), code_verifier: saved.verifier }));
  return true;
}

let refreshing = null;
/** A usable ID token, refreshed first when it is about to expire. Null when signed out (or the refresh token is no longer valid). */
export async function freshIdToken(cfg) {
  const t = tokens.get();
  if (!t) return null;
  if (!isExpiring(t.exp, Date.now())) return t.id;
  if (!t.refresh || !cfg) { tokens.clear(); return null; }
  refreshing ||= tokenCall(cfg, { grant_type: "refresh_token", refresh_token: t.refresh }).then((r) => { keep(r, t); return tokens.get().id; }).catch(() => { tokens.clear(); return null; }).finally(() => { refreshing = null; });
  return refreshing;
}

export function signOut(cfg) { tokens.clear(); if (cfg?.domain) location.assign(logoutUrl(cfg, redirectUri())); }
