import test from "node:test";
import assert from "node:assert/strict";
import * as A from "../js/auth.js";

test("PKCE challenge matches the RFC 7636 example", async () => {
  assert.equal(await A.pkceChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
});

test("random strings are url-safe and different each time", () => {
  const a = A.randomString(64), b = A.randomString(64);
  assert.match(a, /^[A-Za-z0-9_-]{43,}$/); assert.notEqual(a, b);
  assert.equal(A.b64url(new Uint8Array([251, 255, 254])), "-__-");
});

test("reads the payload of a token and decides when to refresh", () => {
  const enc = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const tok = `${enc({ alg: "RS256" })}.${enc({ email: "ü@x.in", exp: 2000 })}.sig`;
  assert.equal(A.jwtPayload(tok).email, "ü@x.in");
  assert.equal(A.jwtPayload("garbage"), null);
  assert.equal(A.isExpiring(2000, 1_000_000), false);          // 1000 s left
  assert.equal(A.isExpiring(2000, 1_950_000), true);           // 50 s left: inside the 60 s margin
  assert.equal(A.isExpiring(undefined, 0), true);
});

test("hosted-page URLs carry PKCE, state and the exact redirect", () => {
  const cfg = { domain: "aceit.auth.ap-south-1.amazoncognito.com", client_id: "c1" };
  const u = new URL(A.authorizeUrl(cfg, "https://app.example/", "st", "ch"));
  assert.equal(u.origin + u.pathname, "https://aceit.auth.ap-south-1.amazoncognito.com/oauth2/authorize");
  assert.deepEqual(Object.fromEntries(u.searchParams), { response_type: "code", client_id: "c1", redirect_uri: "https://app.example/", scope: "openid email", state: "st", code_challenge: "ch", code_challenge_method: "S256" });
  const l = new URL(A.logoutUrl(cfg, "https://app.example/"));
  assert.equal(l.searchParams.get("logout_uri"), "https://app.example/");
});
