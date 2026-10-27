"""One-off administration, run as an ECS task (the database is not reachable from outside the VPC).

    python -m aceit.admin load                 # create the schema and load the question bank into an EMPTY database
    python -m aceit.admin publish-dev          # DEVELOPMENT SHORTCUT: make 2018+ questions live without the publish gate
"""
import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from serve import database_url

SQL = Path(os.environ.get("ACEIT_SQL_DIR", "/app/sql"))
ORDER = ["schema.sql", "seed_paper_sessions.sql", "keys.sql", "tax.sql", "ingest.sql", "tags.sql"]

PUBLISH_DEV = """
UPDATE paper_session SET availability = 'live' WHERE year >= 2018;
UPDATE paper_session SET rank_eligible = true WHERE year >= 2018 AND key_provenance = 'official' AND key_finality = 'final';
UPDATE question q SET status = 'live', rank_eligible = ps.rank_eligible FROM paper_session ps WHERE ps.id = q.session_id AND ps.year >= 2018;"""


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    with psycopg.connect(database_url(), autocommit=True) as conn:
        if cmd == "load":
            if conn.execute("SELECT to_regclass('public.paper') AS t").fetchone()[0]:
                print("refused: the database already has the aceIt schema; this loader only runs on an empty database"); return 1
            for name in ORDER:
                conn.execute((SQL / name).read_text())
                print("loaded", name, flush=True)
            n = conn.execute("SELECT count(*) FROM question").fetchone()[0]
            print(f"done: {n} questions loaded as drafts (nothing is live yet)")
            return 0
        if cmd == "publish-dev":
            conn.execute(PUBLISH_DEV)
            print("2018+ questions are now live WITHOUT the publish gate (development shortcut)")
            return 0
    print(__doc__); return 2


sys.exit(main())
