"""Who is calling. Production: a Cognito JWT (RS256) verified against the pool's public keys.
Local development only: ACEIT_AUTH_MODE=dev trusts an 'X-Dev-User' header. The default is the safe one (jwt)."""
import jwt
from fastapi import HTTPException, Request

from .config import Settings


class JwksCache:
    """Fetches the signing keys once and keeps them. `keys` can be injected in tests."""

    def __init__(self, url: str = "", keys: dict | None = None):
        self.url, self._keys = url, keys

    def key_for(self, kid: str):
        if self._keys is None:
            import httpx
            self._keys = {k["kid"]: k for k in httpx.get(self.url, timeout=5).raise_for_status().json()["keys"]}
        k = self._keys.get(kid)
        if not k:
            raise HTTPException(401, "unknown signing key")
        return jwt.PyJWK(k).key


def verify_token(token: str, settings: Settings, jwks: JwksCache) -> dict:
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":                     # never accept 'none' or a symmetric algorithm
            raise HTTPException(401, "bad token algorithm")
        claims = jwt.decode(token, jwks.key_for(header["kid"]), algorithms=["RS256"],
                            issuer=settings.jwt_issuer, audience=settings.jwt_audience, options={"require": ["exp", "sub", "iss", "aud"]})
        if settings.jwt_token_use and claims.get("token_use") != settings.jwt_token_use:      # an access token is not an ID token: refuse it
            raise HTTPException(401, "wrong token type")
    except HTTPException:
        raise
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token")
    return claims


def caller(request: Request) -> dict:
    """-> {'sub': ..., 'email': ...}. Raises 401. Used as a FastAPI dependency."""
    s: Settings = request.app.state.settings
    if s.auth_mode == "dev":
        who = request.headers.get("X-Dev-User")
        if not who:
            raise HTTPException(401, "dev mode: send an X-Dev-User header")
        return {"sub": f"dev:{who}", "email": f"{who}@dev.local"}
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    c = verify_token(auth[7:], s, request.app.state.jwks)
    return {"sub": c["sub"], "email": c.get("email")}
