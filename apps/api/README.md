# aceIt API

    cd apps/api && uv sync          # once
    .venv/bin/python -m pytest -q   # 35 tests; needs PostgreSQL binaries (set PG_BIN if not auto-found)

Run locally (development only, trusts an X-Dev-User header):

    ACEIT_AUTH_MODE=dev ACEIT_DATABASE_URL=postgresql:///aceit .venv/bin/uvicorn --factory aceit.api.main:create_app --port 8000

Production uses ACEIT_AUTH_MODE=jwt (the default) with ACEIT_JWKS_URL, ACEIT_JWT_ISSUER and ACEIT_JWT_AUDIENCE from the Cognito user pool.

Endpoints (v1): GET /health, /me, /topics/resolve?q= · POST /tests · GET /tests/{id} · POST /attempts · GET /attempts/{id} ·
PUT /attempts/{id}/responses · POST /attempts/{id}/submit · GET /attempts/{id}/result
