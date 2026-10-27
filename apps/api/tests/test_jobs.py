from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from aceit.jobs import runner
from aceit.jobs.runner import Job

NOW = datetime(2026, 12, 1, tzinfo=timezone.utc)


@pytest.fixture
def conn(pg):
    with psycopg.connect(pg, row_factory=dict_row, autocommit=True) as c:
        yield c


def test_sweep_job_closes_an_abandoned_attempt(pg, conn):
    uid = conn.execute("INSERT INTO app_user (cognito_sub) VALUES ('jobuser') ON CONFLICT (cognito_sub) DO UPDATE SET email = NULL RETURNING id::text").fetchone()["id"]
    vids = [r["id"] for r in conn.execute("SELECT current_version_id::text AS id FROM question LIMIT 2").fetchall()]
    tid = conn.execute("INSERT INTO test_instance (paper_id, kind, question_version_ids, duration_s) SELECT id, 'custom', %s::uuid[], 600 FROM paper WHERE code = 'CS' RETURNING id::text", (vids,)).fetchone()["id"]
    aid = conn.execute("INSERT INTO attempt (test_instance_id, user_id, started_at, deadline_at) VALUES (%s::uuid, %s::uuid, %s, %s) RETURNING id::text",
                       (tid, uid, NOW - timedelta(hours=5), NOW - timedelta(hours=2))).fetchone()["id"]
    try:
        r = runner.run_job(pg, Job("sweep", 60, runner.sweep), NOW)
        assert r["status"] == "ok" and r["closed"] >= 1
        assert conn.execute("SELECT status FROM attempt WHERE id = %s::uuid", (aid,)).fetchone()["status"] == "auto_submitted"
        assert runner.run_job(pg, Job("sweep", 60, runner.sweep), NOW)["closed"] == 0                    # nothing left: idempotent
    finally:
        conn.execute("DELETE FROM attempt WHERE id = %s::uuid", (aid,)); conn.execute("DELETE FROM test_instance WHERE id = %s::uuid", (tid,))


def test_a_job_never_runs_twice_at_once(pg):
    import zlib
    with psycopg.connect(pg) as other:                                           # another replica is mid-run: it holds the job's lock
        other.execute("SELECT pg_advisory_xact_lock(%s)", (zlib.crc32(b"sweep"),))
        r = runner.run_job(pg, Job("sweep", 60, runner.sweep), NOW)
        assert r["status"] == "skipped"
        assert runner.run_job(pg, Job("quarantine-other", 60, lambda c, n: {"x": 1}), NOW)["status"] == "ok"   # other jobs are unaffected
    assert runner.run_job(pg, Job("sweep", 60, runner.sweep), NOW)["status"] == "ok"                      # lock released at the end of the transaction


def test_a_failing_job_rolls_back_reports_the_error_and_does_not_stop_the_others(pg, conn):
    def bad(c, now):
        c.execute("INSERT INTO app_user (cognito_sub) VALUES ('should-roll-back')")
        raise RuntimeError("boom")
    r = runner.run_job(pg, Job("bad", 1, bad), NOW)
    assert r["status"] == "error" and "boom" in r["error"]
    assert conn.execute("SELECT count(*) AS n FROM app_user WHERE cognito_sub = 'should-roll-back'").fetchone()["n"] == 0
    jobs = [Job("bad", 100, bad), Job("good", 100, lambda c, n: {"ok": True})]
    nxt = {}
    out = runner.run_due(pg, nxt, 1000, jobs)
    assert [(x["job"], x["status"]) for x in out] == [("bad", "error"), ("good", "ok")]                 # one failure, the other still ran


def test_schedule_runs_each_job_when_due_and_not_before(pg):
    calls = []
    jobs = [Job("a", 10, lambda c, n: calls.append("a") or {}), Job("b", 30, lambda c, n: calls.append("b") or {})]
    nxt = {}
    runner.run_due(pg, nxt, 0, jobs); assert calls == ["a", "b"]
    runner.run_due(pg, nxt, 5, jobs); assert calls == ["a", "b"]                                         # nothing due yet
    runner.run_due(pg, nxt, 10, jobs); assert calls == ["a", "b", "a"]
    runner.run_due(pg, nxt, 31, jobs); assert calls == ["a", "b", "a", "a", "b"]


def test_ai_jobs_do_not_spend_money_unless_asked(pg, monkeypatch):
    monkeypatch.delenv("ACEIT_JOB_SOLVER", raising=False)
    assert runner.run_job(pg, Job("gate", 1, runner.publish_gate), NOW)["skipped"].startswith("ACEIT_JOB_SOLVER")
    r = runner.run_job(pg, Job("quarantine", 1, runner.quarantine), NOW)
    assert r["status"] == "ok" and "pending_solve" in r                                                  # the rules still run; report cases wait for a solver
