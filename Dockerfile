# aceIt: API + web app + jobs in one small image. Build from the repository root:  docker build -t aceit .
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN pip install "fastapi>=0.115" "uvicorn>=0.30" "pydantic>=2.8" "psycopg[binary,pool]>=3.2" "pyjwt[crypto]>=2.9" "httpx>=0.27"
WORKDIR /app
COPY apps/api/serve.py apps/api/serve.py
COPY apps/api/src apps/api/src
COPY apps/web web
COPY data/blueprints data/blueprints
COPY deploy/sql sql
COPY deploy/crops crops
ENV ACEIT_WEB_DIR=/app/web ACEIT_BLUEPRINT=/app/data/blueprints/gate_cs_v1.json ACEIT_CROPS_DIR=/app/crops ACEIT_SQL_DIR=/app/sql PYTHONPATH=/app/apps/api/src:/app/apps/api
RUN useradd -r -u 10001 aceit && chown -R aceit /app
USER aceit
EXPOSE 8000
CMD ["python", "apps/api/serve.py"]
