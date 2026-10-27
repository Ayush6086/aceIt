"""    python -m aceit.quarantine run [--refresh] [--solver gemini]   # evaluate the rules (the scheduled job)
       python -m aceit.quarantine takedown <question_id> "who/why"       # a takedown claim: hides the question at once
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from aceit.gate.runner import LlmSolver
from aceit.quarantine import rules

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = ap.add_subparsers(dest="cmd", required=True)
r = sub.add_parser("run"); r.add_argument("--refresh", action="store_true", help="recompute question_stats first"); r.add_argument("--solver", choices=["gemini"])
t = sub.add_parser("takedown"); t.add_argument("question_id"); t.add_argument("detail")
a = ap.parse_args()
with psycopg.connect(os.environ["ACEIT_DATABASE_URL"], row_factory=dict_row, autocommit=True) as conn:
    if a.cmd == "takedown":
        rules.quarantine(conn, a.question_id, "takedown", a.detail)
        print("hidden")
    else:
        if a.refresh:
            print("stats refreshed for", rules.refresh_stats(conn), "questions")
        print(rules.evaluate(conn, datetime.now(timezone.utc), Path(os.environ.get("ACEIT_CROPS_DIR", ".")), LlmSolver() if a.solver else None))
sys.exit(0)
