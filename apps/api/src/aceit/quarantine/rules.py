"""Automatic quarantine (design §21.3). No person in the loop, and no automatic way back: a quarantined question stays hidden
until someone restores it by hand. Quarantine removes a question from NEWLY built tests (the views only serve live questions);
attempts already started keep their questions and are still scored.

Three triggers, each leaves an unresolved question_flag row as the audit trail:
  takedown                 a takedown claim: hidden at once, no other condition
  ai_disagrees_with_key    >= 3 different students reported it within 7 days AND a fresh 5-solve check does not support the official key
  negative_discrimination  on >= 30 attempts, students who got it right scored LOWER on the rest of the test (a probable bad key)
"""
import math
from datetime import datetime, timedelta
from pathlib import Path

from aceit.gate import checks, runner
from aceit.scoring.attempt import score_attempt
from aceit.platform import store

REPORTS_NEEDED, WINDOW = 3, timedelta(days=7)
MIN_ATTEMPTS, NEGATIVE_BELOW = 30, -0.1


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Correlation of two equal-length lists; None when it is undefined (too few points or no spread)."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx, sy = sum((x - mx) ** 2 for x in xs), sum((y - my) ** 2 for y in ys)
    return None if sx == 0 or sy == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sx * sy)


def refresh_stats(conn) -> int:
    """Recompute question_stats from every finished attempt. Discrimination = correlation between getting the question
    right and the score on the REST of that test, over attempts that answered it.
    ponytail: rescans all attempts; switch to incremental updates when the table is large."""
    qof = {r["v"]: r["q"] for r in conn.execute("SELECT id::text AS v, question_id::text AS q FROM question_version").fetchall()}
    per: dict[str, dict] = {}
    for a in conn.execute("SELECT a.id::text, ti.question_version_ids::text[] AS v FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id "
                          "WHERE a.status IN ('submitted', 'auto_submitted')").fetchall():
        items = store.scoring_items(conn, a["id"], a["v"])
        res = score_attempt(items)
        total = sum(float(o.marks) for _, o in res.per_question)
        spent = {i.question_id: i.time_spent_s for i in items}
        for vid, o in res.per_question:
            if o.status not in ("correct", "wrong"):
                continue
            d = per.setdefault(qof[vid], {"x": [], "y": [], "t": []})
            d["x"].append(1.0 if o.status == "correct" else 0.0); d["y"].append(total - float(o.marks)); d["t"].append(spent.get(vid, 0))
    for q, d in per.items():
        conn.execute(
            """INSERT INTO question_stats (question_id, attempts, correct_rate, avg_time_s, discrimination, updated_at) VALUES (%s::uuid, %s, %s, %s, %s, now())
               ON CONFLICT (question_id) DO UPDATE SET attempts = EXCLUDED.attempts, correct_rate = EXCLUDED.correct_rate,
                   avg_time_s = EXCLUDED.avg_time_s, discrimination = EXCLUDED.discrimination, updated_at = now()""",
            (q, len(d["x"]), sum(d["x"]) / len(d["x"]), sum(d["t"]) / len(d["t"]), pearson(d["y"], d["x"])))
    return len(per)


def quarantine(conn, qid: str, kind: str, detail: str) -> None:
    conn.execute("INSERT INTO question_flag (question_id, kind, detail) VALUES (%s::uuid, %s, %s)", (qid, kind, detail))
    conn.execute("UPDATE question SET status = 'quarantined', rank_eligible = false WHERE id = %s::uuid AND status <> 'quarantined'", (qid,))


def report(conn, question_id: str, reporter_id: str, detail: str | None, now: datetime) -> bool:
    """A student report. Counts once per student per question while open. False = already reported."""
    if conn.execute("SELECT 1 FROM question_flag WHERE question_id = %s::uuid AND reporter_id = %s::uuid AND kind = 'student_report' AND resolved_at IS NULL",
                    (question_id, reporter_id)).fetchone():
        return False
    conn.execute("INSERT INTO question_flag (question_id, kind, reporter_id, detail, created_at) VALUES (%s::uuid, 'student_report', %s::uuid, %s, %s)",
                 (question_id, reporter_id, (detail or "")[:500], now))
    return True


def evaluate(conn, now: datetime, root: Path | None = None, solver=None) -> dict:
    """One pass of all three rules. solver=None means the AI check cannot run, so report-based cases are only listed as pending."""
    out = {"takedown": [], "ai_disagrees_with_key": [], "negative_discrimination": [], "pending_solve": [], "supported_by_ai": []}
    for r in conn.execute("SELECT DISTINCT f.question_id::text AS q FROM question_flag f JOIN question q ON q.id = f.question_id "
                          "WHERE f.kind = 'takedown' AND f.resolved_at IS NULL AND q.status <> 'quarantined'").fetchall():
        conn.execute("UPDATE question SET status = 'quarantined', rank_eligible = false WHERE id = %s::uuid", (r["q"],))
        out["takedown"].append(r["q"])

    for r in conn.execute("""SELECT f.question_id::text AS q FROM question_flag f JOIN question q ON q.id = f.question_id
                             WHERE f.kind = 'student_report' AND f.resolved_at IS NULL AND f.created_at > %s AND q.status = 'live'
                             GROUP BY f.question_id HAVING count(DISTINCT f.reporter_id) >= %s""", (now - WINDOW, REPORTS_NEEDED)).fetchall():
        if solver is None:
            out["pending_solve"].append(r["q"]); continue
        q, imgs = runner.solvable(conn.execute(runner.ONE, (r["q"],)).fetchone(), root)
        s = checks.solve_check(solver, q, imgs) if q["key_type"] != "mta" else None
        if s and s["passed"]:                                    # the AI backs the official key: the reports are most likely mistaken
            conn.execute("UPDATE question_flag SET resolved_at = %s, detail = COALESCE(detail, '') || ' [ai supports key]' WHERE question_id = %s::uuid AND kind = 'student_report' AND resolved_at IS NULL", (now, r["q"]))
            out["supported_by_ai"].append(r["q"])
        else:
            quarantine(conn, r["q"], "ai_disagrees_with_key", f"3+ reports in 7 days; fresh solve: {s}")
            out["ai_disagrees_with_key"].append(r["q"])

    for r in conn.execute("SELECT s.question_id::text AS q, s.attempts, s.discrimination FROM question_stats s JOIN question q ON q.id = s.question_id "
                          "WHERE q.status = 'live' AND s.attempts >= %s AND s.discrimination < %s", (MIN_ATTEMPTS, NEGATIVE_BELOW)).fetchall():
        quarantine(conn, r["q"], "negative_discrimination", f"discrimination {r['discrimination']:.2f} over {r['attempts']} attempts")
        out["negative_discrimination"].append(r["q"])
    return out
