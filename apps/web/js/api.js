// Calls to the API. Production sends the Cognito ID token (refreshed when it is about to expire); development mode sends a name.
import * as auth from "./auth.js";
const KEY = "aceit.user";
export const session = {
  get user() { return auth.signedInAs() || (() => { try { return localStorage.getItem(KEY); } catch { return null; } })(); },
  username: undefined,                                 // the chosen username: undefined = not fetched yet, null = none chosen
  cognito: null,                                       // public sign-in settings from /v1/config, set at start-up (null in development)
  set(u) { try { localStorage.setItem(KEY, u); } catch { /* private window: the name lives for this page only */ this._mem = u; } },
  clear() { try { localStorage.removeItem(KEY); } catch { /* ignore */ } this._mem = null; this.username = undefined; auth.tokens.clear(); },
};

export class ApiError extends Error {
  constructor(status, detail) { super(typeof detail === "string" ? detail : "Something went wrong"); this.status = status; this.detail = detail; }
}

const headers = async () => {
  const token = await auth.freshIdToken(session.cognito);
  if (token) return { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
  const dev = session.user || session._mem;
  return { "Content-Type": "application/json", ...(dev ? { "X-Dev-User": dev } : {}) };
};

export async function api(path, { method = "GET", body } = {}) {
  let res;
  try { res = await fetch("/v1" + path, { method, headers: await headers(), body: body === undefined ? undefined : JSON.stringify(body) }); }
  catch { throw new ApiError(0, "You appear to be offline."); }
  if (res.status === 401) { session.clear(); location.hash = "#/login"; throw new ApiError(401, "Please sign in."); }
  const data = res.status !== 204 && res.headers.get("content-type")?.includes("json") ? await res.json() : null;      // a 204 has no body to parse
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? res.statusText);
  return data;
}

/** Question page images need the sign-in header, so they are fetched and shown from a blob URL. */
export async function loadImage(img, versionId, n) {
  try {
    const res = await fetch(`/v1/questions/${versionId}/images/${n}`, { headers: await headers() });
    if (res.ok) img.src = URL.createObjectURL(await res.blob());
  } catch { /* the stem text is the fallback */ }
}
