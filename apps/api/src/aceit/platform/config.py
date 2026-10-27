"""Settings from environment variables. Nothing secret is stored here and nothing insecure is the default."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    auth_mode: str                  # 'jwt' (production) or 'dev' (local only, trusts an X-Dev-User header)
    jwks_url: str = ""              # Cognito: https://cognito-idp.<region>.amazonaws.com/<pool-id>/.well-known/jwks.json
    jwt_issuer: str = ""
    jwt_audience: str = ""
    full_mock_min_year: int = 2018  # full mocks use the current format only (design §22 policy)
    jwt_token_use: str = ""         # Cognito: 'id' = only ID tokens are accepted (they carry the email); '' = do not check
    cognito_domain: str = ""        # public values the browser needs for the hosted sign-in page (no secrets: the app client has none)
    cognito_client_id: str = ""


def load() -> Settings:
    mode = os.environ.get("ACEIT_AUTH_MODE", "jwt")
    if mode not in ("jwt", "dev"):
        raise RuntimeError("ACEIT_AUTH_MODE must be 'jwt' or 'dev'")
    env = os.environ.get
    # With the pool id, region and app client id, everything else follows from Cognito's fixed URL scheme.
    issuer = f"https://cognito-idp.{env('ACEIT_COGNITO_REGION')}.amazonaws.com/{env('ACEIT_COGNITO_POOL_ID')}" if env("ACEIT_COGNITO_REGION") and env("ACEIT_COGNITO_POOL_ID") else ""
    return Settings(
        database_url=env("ACEIT_DATABASE_URL", "postgresql:///aceit"),
        auth_mode=mode,
        jwks_url=env("ACEIT_JWKS_URL", issuer and issuer + "/.well-known/jwks.json"),
        jwt_issuer=env("ACEIT_JWT_ISSUER", issuer),
        jwt_audience=env("ACEIT_JWT_AUDIENCE", env("ACEIT_COGNITO_CLIENT_ID", "")),
        jwt_token_use=env("ACEIT_JWT_TOKEN_USE", "id"),
        cognito_domain=env("ACEIT_COGNITO_DOMAIN", "").removeprefix("https://").rstrip("/"),
        cognito_client_id=env("ACEIT_COGNITO_CLIENT_ID", ""),
        full_mock_min_year=int(os.environ.get("ACEIT_FULL_MOCK_MIN_YEAR", "2018")),
    )
