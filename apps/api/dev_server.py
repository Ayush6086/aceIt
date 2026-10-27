"""Local development server with REAL data. DEVELOPMENT ONLY: it publishes every question without the publish gate
(which is not built yet) and trusts an X-Dev-User header.

    ../../tools/build_dev_sql.sh            # once: builds build/dev/*.sql from the PDFs
    .venv/bin/python dev_server.py          # then open http://localhost:8000
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "dev"
PG_BIN = next(p for p in ("/Library/PostgreSQL/18/bin", "/opt/homebrew/opt/postgresql@17/bin") if (Path(p) / "initdb").exists())
env = {**os.environ, "PATH": f"{PG_BIN}:{os.environ['PATH']}"}
PORT_PG, PORT = 55440, int(os.environ.get("PORT", "8000"))
data = BUILD / "pgdata"
run = lambda *a: subprocess.run(a, check=True, capture_output=True, text=True, env=env)
psql = lambda *a: run("psql", "-h", str(BUILD), "-p", str(PORT_PG), "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-q", *a)

if not (data / "PG_VERSION").exists():
    run("initdb", "-D", str(data), "-U", "postgres", "--auth=trust", "-E", "UTF8")
fresh = subprocess.run(["pg_ctl", "-D", str(data), "status"], env=env, capture_output=True).returncode != 0
if fresh:
    run("pg_ctl", "-D", str(data), "-o", f"-p {PORT_PG} -k {BUILD} -c listen_addresses=''", "-l", str(BUILD / "pg.log"), "-w", "start")
exists = psql("-d", "postgres", "-At", "-c", "SELECT 1 FROM pg_database WHERE datname = 'aceit'").stdout.strip()
if not exists:
    psql("-c", "CREATE DATABASE aceit")
    for f in (ROOT / "db" / "schema.sql", ROOT / "db" / "seed_paper_sessions.sql", BUILD / "keys.sql", BUILD / "tax.sql", BUILD / "ingest.sql", BUILD / "tags.sql"):
        psql("-d", "aceit", "-f", str(f))
    # DEV ONLY: publish the 2018+ questions so the app has something to serve
    psql("-d", "aceit", "-c", """
      UPDATE paper_session SET availability = 'live' WHERE year >= 2018;
      UPDATE paper_session SET rank_eligible = true WHERE year >= 2018 AND key_provenance = 'official' AND key_finality = 'final';
      UPDATE question q SET status = 'live', rank_eligible = ps.rank_eligible FROM paper_session ps WHERE ps.id = q.session_id AND ps.year >= 2018;""")

# Sign-in with a real email and password (Amazon Cognito) is the default whenever cognito.env exists. The no-password name form is
# only for quick local testing: start with ACEIT_AUTH_MODE=dev to get it.
_cog = Path(__file__).parent / "cognito.env"
if "ACEIT_AUTH_MODE" not in os.environ and _cog.exists():
    for _line in _cog.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
os.environ.setdefault("ACEIT_AUTH_MODE", "dev")
os.environ.update(ACEIT_DATABASE_URL=f"host={BUILD} port={PORT_PG} user=postgres dbname=aceit",
                  ACEIT_CROPS_DIR=os.environ.get("ACEIT_CROPS_DIR", str(Path.home() / "Downloads/GATE/pyq/ingest")))
sys.path.insert(0, str(Path(__file__).parent / "src"))
import logging
import threading
import uvicorn
from aceit.jobs import runner as jobs
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
threading.Thread(target=jobs.loop, args=(os.environ["ACEIT_DATABASE_URL"],), daemon=True).start()   # the scheduled jobs (sweeper, quarantine) run in-process in development
from aceit.api.main import create_app
print(f"aceIt server: http://localhost:{PORT}  (sign-in: " + ("email + password via Cognito" if os.environ["ACEIT_AUTH_MODE"] == "jwt" else "DEVELOPMENT name-only, no password") + ")", flush=True)
uvicorn.run(create_app(), host="127.0.0.1", port=PORT, log_level="warning")
