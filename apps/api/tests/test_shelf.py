import json

import psycopg
import pytest
from psycopg.rows import dict_row

from aceit.api.main import BLUEPRINT
from aceit.testing import shelf
from test_api import H, client, clock, pool, start   # noqa: F401

BP = json.loads(BLUEPRINT.read_text())


@pytest.fixture
def conn(pg):
    with psycopg.connect(pg, row_factory=dict_row, autocommit=True) as c:
        yield c
        c.execute("DELETE FROM attempt WHERE test_instance_id IN (SELECT id FROM test_instance WHERE owner_id IS NULL)")
        c.execute("DELETE FROM test_instance WHERE owner_id IS NULL")                 # leave no shared tests behind for other test modules


def on_shelf(conn):
    return {r["shelf_key"]: r["n"] for r in conn.execute("SELECT shelf_key, count(*) AS n FROM test_instance WHERE shelf_key IS NOT NULL GROUP BY 1").fetchall()}


def test_restock_fills_every_shelf_with_valid_shared_tests_and_is_idempotent(conn):
    r = shelf.restock(conn, BP)
    have = on_shelf(conn)
    assert have["full:practice"] == 4 and all(have.get(f"subject:{s}", 0) == 2 for s in BP["subject_marks"])
    assert sum(r["added"].values()) == sum(have.values())
    t = conn.execute("SELECT question_version_ids, duration_s, rank_eligible, owner_id FROM test_instance WHERE shelf_key = 'full:practice' LIMIT 1").fetchone()
    assert len(t["question_version_ids"]) == 65 and t["duration_s"] == 10800 and t["owner_id"] is None and t["rank_eligible"] is False
    assert len(set(t["question_version_ids"])) == 65
    assert shelf.restock(conn, BP)["added"] == {}                                    # already stocked: nothing to do
    if "full:rank" in have:                                                          # a rank-bearing shelf test is only ever built from rank-eligible questions
        ids = conn.execute("SELECT question_version_ids FROM test_instance WHERE shelf_key = 'full:rank' LIMIT 1").fetchone()["question_version_ids"]
        assert conn.execute("SELECT count(*) AS n FROM v_rank_question WHERE version_id = ANY(%s)", (ids,)).fetchone()["n"] == 65
    else:
        assert any(m.startswith("full:rank") for m in r["cannot_build"])             # reported, never faked


def test_a_quarantined_question_takes_its_tests_off_the_shelf_and_they_are_replaced(conn):
    shelf.restock(conn, BP)
    t = conn.execute("SELECT id::text, question_version_ids::text[] AS v FROM test_instance WHERE shelf_key = 'full:practice' LIMIT 1").fetchone()
    q = conn.execute("SELECT question_id::text AS q FROM question_version WHERE id = %s::uuid", (t["v"][0],)).fetchone()["q"]
    conn.execute("UPDATE question SET status = 'quarantined' WHERE id = %s::uuid", (q,))
    try:
        r = shelf.restock(conn, BP)
        assert r["retired"] >= 1 and r["added"].get("full:practice", 0) >= 1
        assert conn.execute("SELECT shelf_key FROM test_instance WHERE id = %s::uuid", (t["id"],)).fetchone()["shelf_key"] is None
        assert conn.execute("SELECT count(*) AS n FROM test_instance WHERE shelf_key IS NOT NULL AND %s::uuid = ANY(question_version_ids)", (t["v"][0],)).fetchone()["n"] == 0
    finally:
        conn.execute("UPDATE question SET status = 'live' WHERE id = %s::uuid", (q,))


def test_old_shelf_tests_are_retired(conn):
    shelf.restock(conn, BP)
    conn.execute("UPDATE test_instance SET created_at = now() - interval '15 days' WHERE shelf_key = 'full:practice'")
    r = shelf.restock(conn, BP)
    assert r["retired"] >= 4 and r["added"]["full:practice"] == 4


def test_students_get_a_shelf_test_they_have_not_seen_otherwise_a_fresh_one(client, conn):
    shelf.restock(conn, BP)
    key = "full:practice" if not on_shelf(conn).get("full:rank") else "full:rank"
    shelved = {r["id"] for r in conn.execute("SELECT id::text FROM test_instance WHERE shelf_key IS NOT NULL").fetchall()}
    r1 = client.post("/v1/tests", json={"kind": "full"}, headers=H("shelfuser")).json()
    assert r1["id"] in shelved and r1["questions"] == 65
    a = start(client, r1["id"], "shelfuser")
    assert client.get(f"/v1/attempts/{a['id']}", headers=H("shelfuser")).status_code == 200      # a shared test is startable
    client.post(f"/v1/attempts/{a['id']}/submit", headers=H("shelfuser"))
    r2 = client.post("/v1/tests", json={"kind": "full"}, headers=H("shelfuser")).json()
    seen = {r["v"] for r in conn.execute("SELECT unnest(question_version_ids)::text AS v FROM test_instance WHERE id = %s::uuid", (r1["id"],)).fetchall()}
    got = {r["v"] for r in conn.execute("SELECT unnest(question_version_ids)::text AS v FROM test_instance WHERE id = %s::uuid", (r2["id"],)).fetchall()}
    assert r2["id"] != r1["id"] and (r2["id"] not in shelved or not (got & seen))                  # never a shelf test sharing a question with one already taken
    other = client.post("/v1/tests", json={"kind": "full", "seed": 7}, headers=H("shelfuser2")).json()
    assert other["id"] not in shelved                                                              # an explicit seed asks for a specific build: shelf bypassed
    sub = client.post("/v1/tests", json={"kind": "topic", "topics": ["algorithms"], "count": 20}, headers=H("shelfuser3")).json()
    assert sub["id"] in shelved                                                                    # a whole-subject test also comes off the shelf


# ---- paired CS1/CS2-style sets ------------------------------------------------------------------------------
from aceit.platform import store
from aceit.testing.assembler import AssemblyError, build_pair, validate_plan


def test_a_pair_is_two_valid_mocks_with_no_question_in_common(conn):
    pool = store.load_pool(conn, 2018)
    one, two = build_pair(pool, BP, 11, rank_only=False)
    assert len(one.question_ids) == len(two.question_ids) == 65 and not set(one.question_ids) & set(two.question_ids)
    by_id = {c.id: c for c in pool}
    for plan in (one, two):
        assert validate_plan([by_id[i] for i in plan.question_ids], BP, rank_only=False, relaxed=plan.relaxed) == []
    again = build_pair(pool, BP, 11, rank_only=False)
    assert (again[0].question_ids, again[1].question_ids) == (one.question_ids, two.question_ids)           # reproducible from the seed
    with pytest.raises(AssemblyError):                                                                       # all or nothing
        build_pair(pool[:80], BP, 11, rank_only=False)


def test_pairs_are_stocked_served_and_retired_together(client, conn):
    r = shelf.restock(conn, BP)
    have = on_shelf(conn)
    assert have["pair:practice"] == 4                                                                        # 2 pairs = 4 tests
    pairs = conn.execute("SELECT pair_id::text, array_agg(pair_set ORDER BY pair_set) AS sets, count(DISTINCT question_version_ids) AS n FROM test_instance WHERE shelf_key = 'pair:practice' GROUP BY 1").fetchall()
    assert len(pairs) == 2 and all(p["sets"] == [1, 2] for p in pairs)
    # served: both sets, linked, startable
    got = client.post("/v1/test-pairs", json={}, headers=H("pairuser")).json()
    assert [s["set"] for s in got["sets"]] == [1, 2] and got["pair_id"] in {p["pair_id"] for p in pairs} | {r["pair_id"] for r in conn.execute("SELECT pair_id::text FROM test_instance WHERE shelf_key = 'pair:rank'").fetchall()}
    a = start(client, got["sets"][0]["id"], "pairuser")
    client.post(f"/v1/attempts/{a['id']}/submit", headers=H("pairuser"))
    nxt = client.post("/v1/test-pairs", json={}, headers=H("pairuser")).json()                               # one set already taken: that pair is no longer fresh
    assert nxt["pair_id"] != got["pair_id"]
    # a bad question in one set takes the WHOLE pair off the shelf
    victim = conn.execute("SELECT question_version_ids[1]::text AS v, pair_id::text AS p FROM test_instance WHERE shelf_key = 'pair:practice' AND pair_set = 2 LIMIT 1").fetchone()
    q = conn.execute("SELECT question_id::text AS q FROM question_version WHERE id = %s::uuid", (victim["v"],)).fetchone()["q"]
    conn.execute("UPDATE question SET status = 'quarantined' WHERE id = %s::uuid", (q,))
    try:
        shelf.restock(conn, BP)
        assert conn.execute("SELECT count(*) AS n FROM test_instance WHERE pair_id = %s::uuid AND shelf_key IS NOT NULL", (victim["p"],)).fetchone()["n"] == 0
    finally:
        conn.execute("UPDATE question SET status = 'live' WHERE id = %s::uuid", (q,))


def test_pair_on_demand_when_the_shelf_cannot_serve(client, conn):
    r = client.post("/v1/test-pairs", json={"seed": 5}, headers=H("pairuser2"))                              # a seed bypasses the shelf
    assert r.status_code == 201
    s = r.json()["sets"]
    ids = [{x["v"] for x in conn.execute("SELECT unnest(question_version_ids)::text AS v FROM test_instance WHERE id = %s::uuid", (t["id"],)).fetchall()} for t in s]
    assert not ids[0] & ids[1] and all(t["questions"] == 65 for t in s)
    assert conn.execute("SELECT count(*) AS n FROM test_instance WHERE pair_id = %s::uuid AND owner_id IS NOT NULL AND shelf_key IS NULL", (r.json()["pair_id"],)).fetchone()["n"] == 2
    assert client.post("/v1/test-pairs", json={"seed": 5, "rank_only": True}, headers=H("pairuser2")).status_code in (201, 422)   # either, but never a 500


def test_pair_progress_shows_each_set_and_the_students_attempts(client, conn):
    made = client.post("/v1/test-pairs", json={"seed": 21}, headers=H("pairprog")).json()
    st = client.get(f"/v1/test-pairs/{made['pair_id']}", headers=H("pairprog")).json()["sets"]
    assert [s["set"] for s in st] == [1, 2] and all(s["attempt_id"] is None for s in st)
    a = start(client, made["sets"][0]["id"], "pairprog")
    client.post(f"/v1/attempts/{a['id']}/submit", headers=H("pairprog"))
    st = client.get(f"/v1/test-pairs/{made['pair_id']}", headers=H("pairprog")).json()["sets"]
    assert st[0]["status"] == "submitted" and st[0]["max_score"] == 100 and st[1]["attempt_id"] is None
    listed = [x for x in client.get("/v1/attempts", headers=H("pairprog")).json() if x["id"] == a["id"]][0]
    assert listed["pair_id"] == made["pair_id"] and listed["pair_set"] == 1
    assert client.get(f"/v1/test-pairs/{made['pair_id']}", headers=H("someoneelse")).status_code == 404      # an owned pair is private
