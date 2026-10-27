import json
from pathlib import Path

import pytest
from psycopg.rows import dict_row
import psycopg

from aceit.gate import checks, runner


def Q(**kw):
    base = dict(q_type="MCQ", marks=1, display="text", stem="What is 2+2?", crops_ok=True, key_type="mcq", key={"choice": "A"}, key_status="OFFICIAL",
                options=[{"label": c, "text": f"opt {c}"} for c in "ABCD"])
    return {**base, **kw}


def test_structural_accepts_good_and_names_every_defect():
    assert checks.structural(Q()) == []
    assert checks.structural(Q(q_type="NAT", options=None, key_type="nat", key={"min": 1, "max": 2})) == []
    assert checks.structural(Q(display="image", stem="", options=None)) == []                    # image mode: the picture is the question
    for bad, why in [(Q(marks=3), "marks"), (Q(crops_ok=False), "image missing"), (Q(stem=" "), "empty"), (Q(options=Q()["options"][:3]), "four"),
                     (Q(key={"choice": "E"}), "outside"), (Q(key_type="msq"), "does not fit"), (Q(key_status="UNCERTAIN"), "key status"),
                     (Q(q_type="NAT", options=Q()["options"], key_type="nat", key={"min": 1, "max": 2}), "has options"),
                     (Q(q_type="NAT", options=None, key_type="nat", key={"min": 3, "max": 2}), "reversed"),
                     (Q(q_type="MSQ", key_type="msq", key={"choices": []}), "outside")]:
        assert any(why in p for p in checks.structural(bad)), (why, checks.structural(bad))
    assert checks.structural(Q(key={"any_of": [{"choice": "A"}, {"choice": "B"}]})) == []


def test_reader_agreement():
    assert checks.reader_agreement("The cat sat 12", "the cat sat 12 extra words") == 1.0       # extra words from the page are fine
    assert checks.reader_agreement("a b c d", "a b") == 0.5
    assert checks.reader_agreement("x x x", "x") == pytest.approx(1 / 3)                         # repeats count
    assert checks.reader_agreement("", "anything") == 1.0


def fixed(answer):
    return lambda q, imgs: answer


def test_solve_needs_agreement_and_the_official_key():
    q = Q()
    assert checks.solve_check(fixed({"choice": "A"}), q, [])["passed"]
    wrong = checks.solve_check(fixed({"choice": "B"}), q, [])
    assert wrong["agree"] == 5 and wrong["matches_key"] is False and not wrong["passed"]        # confident but not the key: a likely misread
    seq = iter([{"choice": "A"}] * 3 + [{"choice": "B"}] * 2)
    assert not checks.solve_check(lambda q, i: next(seq), q, [])["passed"]                       # 3 of 5 is not enough
    seq = iter([{"choice": "A"}] * 4 + [None])
    assert checks.solve_check(lambda q, i: next(seq), q, [])["passed"]                           # 4 of 5 is
    boom = checks.solve_check(lambda q, i: 1 / 0, q, [])
    assert boom["agree"] == 0 and not boom["passed"]                                             # errors are not agreement
    nat = Q(q_type="NAT", options=None, key_type="nat", key={"min": 1.9, "max": 2.1}, marks=2)
    assert checks.solve_check(fixed({"value": 2}), nat, [])["passed"]


def test_decision_table():
    ok = {"passed": True}
    assert checks.decide([], 0.99, ok, "mcq") == {"status": "live", "rank_ok": True, "reasons": []}
    assert checks.decide([], None, ok, "mcq")["rank_ok"] is True                                  # image mode needs no text reader
    d = checks.decide([], 0.5, ok, "mcq")
    assert d["status"] == "live" and d["rank_ok"] is False and "second reader" in d["reasons"][0]  # practice only
    assert checks.decide([], 0.99, None, "mcq")["status"] == "held"                               # no AI solve = never published
    assert checks.decide([], 0.99, {"passed": False}, "mcq")["status"] == "held"
    assert checks.decide(["marks 3"], 0.99, ok, "mcq")["status"] == "held"
    assert checks.decide([], None, None, "mta")["status"] == "live"                               # marks-to-all needs no solve


# ---- against the real schema (temp PostgreSQL) --------------------------------------------------------------
@pytest.fixture
def held(pg, tmp_path):
    """Three real-shaped questions made 'held' with a crop file each; restored afterwards so other tests are unaffected."""
    with psycopg.connect(pg, row_factory=dict_row, autocommit=True) as c:
        rows = c.execute("""SELECT q.id::text AS qid, qv.id::text AS vid FROM question q JOIN question_version qv ON qv.id = q.current_version_id
                            JOIN paper_session ps ON ps.id = q.session_id WHERE ps.year = 2024 AND ps.session_code = 'CS1' AND q.q_type = 'MCQ' ORDER BY q.number LIMIT 3""").fetchall()
        ids = [r["qid"] for r in rows]
        (tmp_path / "x").mkdir()
        c.execute("ALTER TABLE question_version DISABLE TRIGGER USER")                           # fixture only: versions are immutable by design
        for i, r in enumerate(rows):
            (tmp_path / "x" / f"{i}.png").write_bytes(b"png")
            c.execute("UPDATE question_version SET figures = %s::jsonb, extraction = '{\"display\":\"text\"}' WHERE id = %s::uuid",
                      (json.dumps([{"path": f"ingest/x/{i}.png"}]), r["vid"]))
        c.execute("UPDATE question SET status = 'held' WHERE id = ANY(%s::uuid[])", (ids,))
        yield c, rows, tmp_path
        c.execute("UPDATE question SET status = 'live' WHERE id = ANY(%s::uuid[])", (ids,))
        c.execute("UPDATE question_version SET figures = '[]', extraction = '{\"display\":\"text\"}' WHERE id = ANY(%s::uuid[])", ([r["vid"] for r in rows],))
        c.execute("DELETE FROM ai_check WHERE question_version_id = ANY(%s::uuid[])", ([r["vid"] for r in rows],))
        c.execute("ALTER TABLE question_version ENABLE TRIGGER USER")


def test_runner_publishes_only_what_the_solver_supports(held):
    c, rows, tmp = held
    root = tmp
    t = runner.run(c, root, solver=fixed({"choice": "A"}), apply=True)                           # synthetic key is MCQ=A
    assert t["live"] >= 3 and t["held"] == 0
    st = {r["qid"]: c.execute("SELECT status FROM question WHERE id = %s::uuid", (r["qid"],)).fetchone()["status"] for r in rows}
    assert set(st.values()) == {"live"}
    assert c.execute("SELECT count(*) AS n FROM ai_check WHERE question_version_id = %s::uuid", (rows[0]["vid"],)).fetchone()["n"] == 1
    assert c.execute("SELECT extraction->'gate'->>'status' AS s FROM question_version WHERE id = %s::uuid", (rows[0]["vid"],)).fetchone()["s"] == "live"


def test_runner_holds_when_the_solver_disagrees_or_is_missing_and_never_touches_live(held):
    c, rows, tmp = held
    t = runner.run(c, tmp, solver=fixed({"choice": "B"}), apply=True)
    assert t["live"] == 0 and t["held"] >= 3
    assert c.execute("SELECT status FROM question WHERE id = %s::uuid", (rows[0]["qid"],)).fetchone()["status"] == "held"
    dry = runner.run(c, tmp)                                                                # dry run: measures, writes nothing
    assert "ai solve not run" in dry["reasons"] and dry["live"] == 0
    assert c.execute("SELECT status FROM question WHERE id = %s::uuid", (rows[0]["qid"],)).fetchone()["status"] == "held"
    c.execute("UPDATE question SET status = 'quarantined' WHERE id = %s::uuid", (rows[1]["qid"],))
    runner.run(c, tmp, solver=fixed({"choice": "A"}), apply=True)
    assert c.execute("SELECT status FROM question WHERE id = %s::uuid", (rows[1]["qid"],)).fetchone()["status"] == "quarantined"   # no automatic un-quarantine
