#!/usr/bin/env python3
"""A local stand-in for the Cognito hosted sign-in page, for testing the real sign-in code without an AWS account.
It implements only what aceIt uses: /oauth2/authorize (auto-signs in a test user), /oauth2/token (authorization_code with
a real PKCE check, and refresh_token), /logout and the JWKS. It issues RS256 ID tokens shaped like Cognito's.

    python tools/fake_cognito.py 9000
then run the API with:  ACEIT_AUTH_MODE=jwt ACEIT_JWT_ISSUER=http://localhost:9000/pool ACEIT_JWKS_URL=http://localhost:9000/pool/.well-known/jwks.json
                        ACEIT_COGNITO_CLIENT_ID=testclient ACEIT_COGNITO_DOMAIN=localhost:9000
DEVELOPMENT ONLY. It signs in anyone.
"""
import base64
import hashlib
import json
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse, urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
ISS, CLIENT, TTL = f"http://localhost:{PORT}/pool", "testclient", int(sys.argv[2]) if len(sys.argv) > 2 else 3600
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())), "kid": "k1", "alg": "RS256", "use": "sig"}
codes, refresh = {}, {}


def id_token(email):
    now = int(time.time())
    return jwt.encode({"sub": "sub-" + email, "email": email, "email_verified": True, "iss": ISS, "aud": CLIENT, "token_use": "id", "iat": now, "exp": now + TTL},
                      KEY, algorithm="RS256", headers={"kid": "k1"})


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body=b"", headers=None):
        self.send_response(code)
        for k, v in {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", **(headers or {})}.items():
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def do_OPTIONS(self): self.send(204)

    def do_GET(self):
        u, q = urlparse(self.path), {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        if u.path == "/pool/.well-known/jwks.json":
            return self.send(200, json.dumps({"keys": [JWK]}).encode(), {"Content-Type": "application/json"})
        if u.path == "/oauth2/authorize":
            if q.get("client_id") != CLIENT or q.get("code_challenge_method") != "S256" or "code_challenge" not in q:
                return self.send(400, b"bad authorize request")
            code = secrets.token_urlsafe(16)
            codes[code] = (q["code_challenge"], q["redirect_uri"], "test.student@example.com")
            return self.send(302, headers={"Location": q["redirect_uri"] + "?" + urlencode({"code": code, "state": q.get("state", "")})})
        if u.path == "/logout":
            return self.send(302, headers={"Location": q.get("logout_uri", "/")})
        self.send(404)

    def do_POST(self):
        f = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()).items()}
        out = lambda o: self.send(200, json.dumps(o).encode(), {"Content-Type": "application/json"})
        if f.get("client_id") != CLIENT:
            return self.send(400, b'{"error":"invalid_client"}')
        if f.get("grant_type") == "authorization_code":
            ch, redir, email = codes.pop(f.get("code", ""), (None, None, None))
            verifier_ok = ch and base64.urlsafe_b64encode(hashlib.sha256(f.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode() == ch
            if not verifier_ok or redir != f.get("redirect_uri"):
                return self.send(400, b'{"error":"invalid_grant"}')
            r = secrets.token_urlsafe(24); refresh[r] = email
            return out({"id_token": id_token(email), "access_token": "opaque", "refresh_token": r, "expires_in": TTL, "token_type": "Bearer"})
        if f.get("grant_type") == "refresh_token" and f.get("refresh_token") in refresh:
            return out({"id_token": id_token(refresh[f["refresh_token"]]), "access_token": "opaque", "expires_in": TTL, "token_type": "Bearer"})   # no new refresh token, like Cognito
        self.send(400, b'{"error":"invalid_grant"}')


if __name__ == "__main__":
    print(f"fake Cognito on http://localhost:{PORT} (id tokens live {TTL}s)", flush=True)
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
