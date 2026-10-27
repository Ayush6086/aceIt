"""Production entry point (the container runs this). Builds the database URL from the pieces ECS injects, starts the API,
and (ACEIT_RUN_JOBS=1) the scheduled jobs in a background thread; the jobs take advisory locks, so several containers are safe."""
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from psycopg.conninfo import make_conninfo


def database_url() -> str:
    if os.environ.get("ACEIT_DATABASE_URL"):
        return os.environ["ACEIT_DATABASE_URL"]
    return make_conninfo(host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"), user=os.environ["DB_USER"],
                         password=os.environ["DB_PASSWORD"], dbname=os.environ.get("DB_NAME", "aceit"), sslmode="require")


if __name__ == "__main__":
    os.environ["ACEIT_DATABASE_URL"] = database_url()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    import uvicorn
    from aceit.api.main import create_app
    if os.environ.get("ACEIT_RUN_JOBS") == "1":
        from aceit.jobs import runner
        threading.Thread(target=runner.loop, args=(os.environ["ACEIT_DATABASE_URL"],), daemon=True).start()
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_level="info", proxy_headers=True, forwarded_allow_ips="*")
