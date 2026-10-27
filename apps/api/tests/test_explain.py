import json

import psycopg
import pytest
from psycopg.rows import dict_row

from aceit import explain
from test_api import H, client, clock, new_test, pool, start   # noqa: F401

GOOD = "The key idea is that circular wait needs a cycle in the resource graph. Check each process in turn and follow what it holds and what it waits for.\nFINAL ANSWER: "


def Q(**kw):
    return {**dict(q_type="MCQ", marks=1, key_type="mcq", key={"choice": "B"}), **kw}


def test_official_answer_in_words():
    assert explain.key_text("mcq", {"choice": "B"}) == "B"
    assert explain.key_text("msq", {"choices": ["C", "A"]}) == "A, C"
    assert explain.key_text("nat", {"min": 2, "max": 2}) == "2" and explain.key_text("nat", {"min": 2.5, "max": 3}) == "2.5 to 3"
    assert explain.key_text("mcq", {"any_of": [{"choice": "A"}, {"choice": "B"}]}) == "A or B"
    assert explain.key_text("mta", None) == ""


def test_an_explanation_is_kept_only_if_it_reaches_the_official_answer():
    body, why = explain.accept(Q(), GOOD + '{"choice": "B"}')
    assert why == "ok" and body.startswith("The key idea") and "FINAL ANSWER" not in body
    assert explain.accept(Q(), GOOD + '{"choice": "C"}')[1] == "its answer is not the official answer"          # most likely a misread question
    assert explain.accept(Q(), GOOD.replace("FINAL ANSWER: ", ""))[1] == "no final answer"
    assert explain.accept(Q(), "Too short.\nFINAL ANSWER: " + '{"choice": "B"}')[1] == "explanation too short or too long"
    assert explain.accept(Q(), GOOD + "{not json}")[1] == "no final answer"
    nat = Q(q_type="NAT", marks=2, key_type="nat", key={"min": 2.4, "max": 2.6})
    assert explain.accept(nat, GOOD + '{"value": 2.5}')[1] == "ok" and explain.accept(nat, GOOD + '{"value": 3}')[1] != "ok"
    msq = Q(q_type="MSQ", key_type="msq", key={"choices": ["A", "C"]})
    assert explain.accept(msq, GOOD + '{"choices": ["C", "A"]}')[1] == "ok" and explain.accept(msq, GOOD + '{"choices": ["A"]}')[1] != "ok"


@pytest.fixture
def conn(pg):
    with psycopg.connect(pg, row_factory=dict_row, autocommit=True) as c:
        yield c
        c.execute("UPDATE question_version SET solution_md = NULL, solution_src = NULL")


def writer(answers):
    """A fake explainer: answers by question type with the given responses."""
    def f(q, imgs, official):
        return GOOD + json.dumps(answers[q["q_type"]])
    return f


RIGHT = {"MCQ": {"choice": "A"}, "MSQ": {"choices": ["A", "B"]}, "NAT": {"value": 1}}        # the synthetic bank's keys
WRONG = {"MCQ": {"choice": "B"}, "MSQ": {"choices": ["A"]}, "NAT": {"value": 9}}


def test_the_writer_stores_checked_explanations_and_rejects_the_rest(conn, tmp_path):
    out = explain.run(conn, tmp_path, writer(WRONG), limit=6)
    assert out["stored"] == 0 and out["seen"] == 6 and out["rejected"] == {"its answer is not the official answer": 6}
    assert conn.execute("SELECT count(*) AS n FROM question_version WHERE solution_md IS NOT NULL").fetchone()["n"] == 0
    out = explain.run(conn, tmp_path, writer(RIGHT), limit=6)
    assert out["stored"] == 6
    r = conn.execute("SELECT solution_md, solution_src, extraction->'explanation'->>'checked_against_official_key' AS ok FROM question_version WHERE solution_md IS NOT NULL LIMIT 1").fetchone()
    assert r["solution_src"] == "ai" and r["ok"] == "true" and "FINAL ANSWER" not in r["solution_md"]
    again = explain.run(conn, tmp_path, writer(RIGHT), limit=6)                                   # already explained: picks the next ones, never rewrites
    assert again["seen"] == 6 and conn.execute("SELECT count(*) AS n FROM question_version WHERE solution_md IS NOT NULL").fetchone()["n"] == 12

    def boom(q, i, o): raise RuntimeError("network")
    assert explain.run(conn, tmp_path, boom, limit=2)["rejected"] == {"call failed: RuntimeError": 2}


def test_students_see_explanations_only_after_the_test_is_over(client, conn, clock):
    t = new_test(client, user="reader", kind="topic", topics=["operating-system"], count=5, seed=77)
    a = start(client, t["id"], "reader")
    vids = [q["id"] for q in a["questions"]]
    conn.execute("UPDATE question_version SET solution_md = 'Explained: follow the cycle in the graph.', solution_src = 'ai' WHERE id = ANY(%s::uuid[])", (vids[:2],))
    assert "Explained" not in json.dumps(a) and "solution" not in json.dumps(a["questions"]) and "explanation" not in json.dumps(a["questions"])     # nothing while it runs
    assert client.get(f"/v1/attempts/{a['id']}/review", headers=H("reader")).status_code == 409
    client.post(f"/v1/attempts/{a['id']}/submit", headers=H("reader"))
    rv = client.get(f"/v1/attempts/{a['id']}/review", headers=H("reader")).json()
    assert [bool(q["explanation"]) for q in rv] == [True, True, False, False, False]
    assert rv[0]["explanation"].startswith("Explained")
