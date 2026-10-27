import json
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from aceit.quarantine import rules
from test_api import H, client, clock, new_test, pool, start   # noqa: F401  (fixtures and helpers)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def test_pearson():
    assert rules.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert rules.pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)
    assert rules.pearson([1, 1, 1], [1, 2, 3]) is None and rules.pearson([1, 2], [1, 2]) is None


@pytest.fixture
def conn(pg):
    with psycopg.connect(pg, row_factory=dict_row, autocommit=True) as c:
        yield c


@pytest.fixture
def victim(conn):
    """A fresh live question to quarantine; every flag and the status are put back afterwards."""
    r = conn.execute("SELECT q.id::text AS q, qv.id::text AS v FROM question q JOIN question_version qv ON qv.id = q.current_version_id "
                     "JOIN paper_session ps ON ps.id = q.session_id WHERE ps.year = 2022 AND q.q_type = 'MCQ' ORDER BY q.number LIMIT 1").fetchone()
    yield r
    conn.execute("DELETE FROM question_flag WHERE question_id = %s::uuid", (r["q"],))
    conn.execute("DELETE FROM question_stats WHERE question_id = %s::uuid", (r["q"],))
    conn.execute("UPDATE question SET status = 'live' WHERE id = %s::uuid", (r["q"],))
    conn.execute("DELETE FROM ai_check WHERE question_version_id = %s::uuid", (r["v"],))


def status(conn, q):
    return conn.execute("SELECT status FROM question WHERE id = %s::uuid", (q,)).fetchone()["status"]


def students(conn, n):
    return [conn.execute("INSERT INTO app_user (cognito_sub) VALUES (%s) ON CONFLICT (cognito_sub) DO UPDATE SET email = NULL RETURNING id::text", (f"reporter{i}",)).fetchone()["id"] for i in range(n)]


def crops(conn, v, tmp_path):
    """Give the question a page image so the solve check can run (versions are immutable, so bypass the trigger for the fixture)."""
    (tmp_path / "x").mkdir(exist_ok=True); (tmp_path / "x" / "a.png").write_bytes(b"png")
    conn.execute("ALTER TABLE question_version DISABLE TRIGGER USER")
    conn.execute("UPDATE question_version SET figures = %s::jsonb WHERE id = %s::uuid", (json.dumps([{"path": "ingest/x/a.png"}]), v))
    conn.execute("ALTER TABLE question_version ENABLE TRIGGER USER")


def test_takedown_hides_at_once_and_nothing_restores_it(conn, victim):
    rules.quarantine(conn, victim["q"], "takedown", "claim from X")
    assert status(conn, victim["q"]) == "quarantined"
    rules.evaluate(conn, NOW)
    assert status(conn, victim["q"]) == "quarantined"                          # a later pass never un-quarantines
    assert conn.execute("SELECT count(*) AS n FROM v_servable_question WHERE question_id = %s::uuid", (victim["q"],)).fetchone()["n"] == 0


def test_reports_need_three_different_students_within_seven_days_and_a_failed_solve(conn, victim, tmp_path):
    crops(conn, victim["v"], tmp_path)
    u = students(conn, 4)
    for x in (u[0], u[0], u[1]):                                               # the same student twice counts once
        rules.report(conn, victim["q"], x, "key looks wrong", NOW)
    assert rules.report(conn, victim["q"], u[0], "again", NOW) is False
    assert rules.evaluate(conn, NOW, tmp_path, solver=lambda q, i: {"choice": "B"})["ai_disagrees_with_key"] == []        # only 2 students
    rules.report(conn, victim["q"], u[2], None, NOW - timedelta(days=8))       # too old to count
    assert status(conn, victim["q"]) == "live" and rules.evaluate(conn, NOW, tmp_path, solver=lambda q, i: {"choice": "B"})["ai_disagrees_with_key"] == []
    rules.report(conn, victim["q"], u[3], None, NOW - timedelta(days=1))      # third student inside the window
    assert rules.evaluate(conn, NOW, tmp_path)["pending_solve"] == [victim["q"]]                                          # no solver: listed, not decided
    assert status(conn, victim["q"]) == "live"
    # the AI backs the official key (synthetic key is A): reports are closed, the question stays live
    assert rules.evaluate(conn, NOW, tmp_path, solver=lambda q, i: {"choice": "A"})["supported_by_ai"] == [victim["q"]]
    assert status(conn, victim["q"]) == "live"
    # reports come back later, and now the AI does not support the key: quarantined
    for x in u[:3]:
        rules.report(conn, victim["q"], x, "still wrong", NOW)
    out = rules.evaluate(conn, NOW, tmp_path, solver=lambda q, i: {"choice": "C"})
    assert out["ai_disagrees_with_key"] == [victim["q"]] and status(conn, victim["q"]) == "quarantined"
    assert conn.execute("SELECT count(*) AS n FROM question_flag WHERE question_id = %s::uuid AND kind = 'ai_disagrees_with_key'", (victim["q"],)).fetchone()["n"] == 1


def test_negative_discrimination_needs_enough_attempts(conn, victim):
    ins = lambda n, d: conn.execute("INSERT INTO question_stats (question_id, attempts, discrimination) VALUES (%s::uuid, %s, %s) ON CONFLICT (question_id) DO UPDATE SET attempts = EXCLUDED.attempts, discrimination = EXCLUDED.discrimination", (victim["q"], n, d))
    ins(10, -0.6); assert victim["q"] not in rules.evaluate(conn, NOW)["negative_discrimination"]             # too few attempts
    ins(60, 0.2);  assert victim["q"] not in rules.evaluate(conn, NOW)["negative_discrimination"]             # healthy
    ins(60, -0.3); assert victim["q"] in rules.evaluate(conn, NOW)["negative_discrimination"]
    assert status(conn, victim["q"]) == "quarantined"


def test_students_can_report_only_what_they_were_given_and_refresh_computes_stats(client, clock, conn):
    t = new_test(client, user="rita", kind="topic", topics=["operating-system"], count=6, seed=3)
    a = start(client, t["id"], "rita")
    vid = a["questions"][0]["id"]
    assert client.post(f"/v1/questions/{vid}/report", json={"detail": "x"}, headers=H("rita")).status_code == 404       # test not finished yet
    client.post(f"/v1/attempts/{a['id']}/submit", headers=H("rita"))
    assert client.post(f"/v1/questions/{vid}/report", json={"detail": "key wrong?"}, headers=H("rita")).json() == {"recorded": True}
    assert client.post(f"/v1/questions/{vid}/report", json={}, headers=H("rita")).json() == {"recorded": False}
    assert client.post(f"/v1/questions/{vid}/report", json={}, headers=H("sam")).status_code == 404                        # someone who never had it
    assert rules.refresh_stats(conn) >= 0                                      # one all-unattempted attempt contributes no rows, but must not fail
    q = conn.execute("SELECT question_id::text AS q FROM question_version WHERE id = %s::uuid", (vid,)).fetchone()["q"]
    conn.execute("DELETE FROM question_flag WHERE question_id = %s::uuid", (q,))


def test_refresh_stats_computes_rate_attempts_and_discrimination(conn):
    qs = conn.execute("SELECT q.id::text AS q, qv.id::text AS v FROM question q JOIN question_version qv ON qv.id = q.current_version_id JOIN paper_session ps ON ps.id = q.session_id "
                      "WHERE ps.year = 2022 AND q.q_type = 'MCQ' AND q.marks = 1 ORDER BY q.number LIMIT 3").fetchall()
    tid = conn.execute("INSERT INTO test_instance (paper_id, kind, question_version_ids, duration_s) SELECT id, 'custom', %s::uuid[], 600 FROM paper WHERE code = 'CS' RETURNING id::text",
                       ([x["v"] for x in qs],)).fetchone()["id"]
    users = students(conn, 6)
    # students 0-2 answer every question right (key A), students 3-5 answer every question wrong: each question should discriminate positively
    for i, u in enumerate(users):
        aid = conn.execute("INSERT INTO attempt (test_instance_id, user_id, status, submitted_at, deadline_at) VALUES (%s::uuid, %s::uuid, 'submitted', now(), now() + interval '1 hour') RETURNING id::text", (tid, u)).fetchone()["id"]
        for x in qs:
            choice = "A" if (i < 3) else "B"
            conn.execute("INSERT INTO attempt_response (attempt_id, question_version_id, response, palette_status, time_spent_s) VALUES (%s::uuid, %s::uuid, %s, 'answered', 30)",
                         (aid, x["v"], psycopg.types.json.Jsonb({"choice": choice})))
    try:
        rules.refresh_stats(conn)
        s = conn.execute("SELECT attempts, correct_rate, avg_time_s, discrimination FROM question_stats WHERE question_id = %s::uuid", (qs[0]["q"],)).fetchone()
        assert s["attempts"] >= 6 and s["avg_time_s"] > 0
        assert 0 < s["correct_rate"] < 1 and s["discrimination"] > 0.5            # right answers go with higher scores on the rest of the test
    finally:
        conn.execute("DELETE FROM attempt WHERE test_instance_id = %s::uuid", (tid,))
        conn.execute("DELETE FROM test_instance WHERE id = %s::uuid", (tid,))
        conn.execute("DELETE FROM question_stats WHERE question_id = ANY(%s::uuid[])", ([x["q"] for x in qs],))
