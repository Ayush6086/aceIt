"""Scheduled jobs (design §21.2, §21.3, §21.4): the sweeper, the quarantine rules, the publish gate and the test shelf, run unattended.

    python -m aceit.jobs                 # run forever: every job on its own interval
    python -m aceit.jobs --once sweep    # run one job now and exit (what EventBridge -> ECS would call on AWS)

Safe to run several copies: each job takes a Postgres advisory lock for the length of its transaction, so a job never runs
twice at once, and a failed job rolls back completely and is simply tried again on its next turn. AI-backed work (the gate,
and the solve step of quarantine) spends money, so it runs only when ACEIT_JOB_SOLVER=gemini is set (with GEMINI_API_KEY).
"""
import json
import logging
import os
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import psycopg
from psycopg.rows import dict_row

from aceit.gate import runner as gate
from aceit.platform import store
from aceit.testing.shelf import restock
from aceit.quarantine import rules

log = logging.getLogger("aceit.jobs")


@dataclass(frozen=True)
class Job:
    name: str
    every_s: int
    fn: Callable          # (conn, now) -> dict


def _ai_enabled() -> bool:
    return os.environ.get("ACEIT_JOB_SOLVER", "") in ("llm", "gemini")


def _solver():
    return gate.LlmSolver() if _ai_enabled() else None


def _crops() -> Path:
    return Path(os.environ.get("ACEIT_CROPS_DIR", "."))


def sweep(conn, now):
    return {"closed": store.sweep_expired(conn, now)}


def quarantine(conn, now):
    stats = rules.refresh_stats(conn)
    return {"stats_refreshed": stats, **{k: len(v) for k, v in rules.evaluate(conn, now, _crops(), _solver()).items()}}


def publish_gate(conn, now):
    solver = _solver()
    if not solver:
        return {"skipped": "ACEIT_JOB_SOLVER is not set"}
    t = gate.run(conn, _crops(), solver, use_ocr=True, limit=int(os.environ.get("ACEIT_GATE_BATCH", "100")), apply=True)   # a bounded batch per turn caps the AI spend
    return {k: v for k, v in t.items() if k != "reasons"}


def explanations(conn, now):
    if os.environ.get("ACEIT_EXPLAIN") != "1":               # its own switch: the publish gate uses far more calls and must not eat the same quota
        return {"skipped": "ACEIT_EXPLAIN is not set to 1"}
    from aceit.explain import LlmExplainer, run as write
    r = write(conn, _crops(), LlmExplainer(), limit=int(os.environ.get("ACEIT_EXPLAIN_BATCH", "50")))      # a bounded batch per turn caps the AI spend
    return {"seen": r["seen"], "stored": r["stored"], "rejected": sum(r["rejected"].values())}


def shelf(conn, now):
    from aceit.api.main import BLUEPRINT
    r = restock(conn, json.loads(BLUEPRINT.read_text()))
    return {"retired": r["retired"], "added": sum(r["added"].values()), "cannot_build": len(r["cannot_build"])}


JOBS = [Job("sweep", 60, sweep), Job("quarantine", 900, quarantine), Job("gate", 3600, publish_gate), Job("shelf", 86400, shelf), Job("explain", 21600, explanations)]


def run_job(url: str, job: Job, now: datetime | None = None) -> dict:
    """One run of one job. Returns {"job", "status": ok | skipped | error, ...}. Never raises."""
    t0 = time.monotonic()
    try:
        with psycopg.connect(url, row_factory=dict_row) as conn:                      # one transaction: commit on success, roll back on error
            if not conn.execute("SELECT pg_try_advisory_xact_lock(%s) AS got", (zlib.crc32(job.name.encode()),)).fetchone()["got"]:
                return {"job": job.name, "status": "skipped", "why": "already running elsewhere"}
            out = job.fn(conn, now or datetime.now(timezone.utc))
        return {"job": job.name, "status": "ok", "seconds": round(time.monotonic() - t0, 2), **out}
    except Exception as e:                                                            # isolate: one broken job must not stop the others
        log.exception("job %s failed", job.name)
        return {"job": job.name, "status": "error", "error": f"{type(e).__name__}: {e}"}


def run_due(url: str, next_at: dict[str, float], now_s: float, jobs=JOBS) -> list[dict]:
    """Run every job whose time has come and schedule its next turn (even after a failure, so a broken job is not retried in a tight loop)."""
    out = []
    for j in jobs:
        if now_s >= next_at.get(j.name, 0):
            out.append(run_job(url, j))
            next_at[j.name] = now_s + j.every_s
    return out


def loop(url: str, tick_s: float = 5, stop=lambda: False) -> None:
    next_at: dict[str, float] = {}
    while not stop():
        for r in run_due(url, next_at, time.monotonic()):
            (log.warning if r["status"] == "error" else log.info)("job %s", r)
        time.sleep(tick_s)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", choices=[j.name for j in JOBS], help="run one job now and exit")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    url = os.environ["ACEIT_DATABASE_URL"]
    if a.once:
        r = run_job(url, next(j for j in JOBS if j.name == a.once))
        print(r)
        return 0 if r["status"] != "error" else 1
    log.info("job runner started: %s", ", ".join(f"{j.name} every {j.every_s}s" for j in JOBS))
    loop(url)
    return 0
