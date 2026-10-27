"""End-to-end API tests against a real PostgreSQL (see conftest.py)."""
import json
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from aceit.api.main import create_app
from aceit.platform import store
from aceit.platform.auth import JwksCache
from aceit.platform.config import Settings

T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def pool(pg):
    p = ConnectionPool(pg, kwargs={"row_factory": dict_row}, min_size=1, max_size=5, open=True)
    yield p
    p.close()


@pytest.fixture
def clock():
    return {"now": T0}


@pytest.fixture
def client(pool, clock):
    app = create_app(Settings("unused", "dev"), pool, clock=lambda: clock["now"])
    return TestClient(app)


def H(user="alice"):
    return {"X-Dev-User": user}


def new_test(client, user="alice", **body):
    r = client.post("/v1/tests", json=body, headers=H(user))
    assert r.status_code == 201, r.text
    return r.json()


def start(client, test_id, user="alice"):
    r = client.post("/v1/attempts", json={"test_id": test_id}, headers=H(user))
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- authentication
def test_dev_mode_needs_a_header_and_jwt_mode_needs_a_valid_token(pool):
    dev = TestClient(create_app(Settings("x", "dev"), pool))
    assert dev.get("/v1/me").status_code == 401
    assert dev.get("/v1/me", headers=H()).status_code == 200

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())); jwk.update(kid="k1", alg="RS256", use="sig")
    s = Settings("x", "jwt", jwt_issuer="https://issuer.example", jwt_audience="aceit", jwt_token_use="id")
    c = TestClient(create_app(s, pool, jwks=JwksCache(keys={"k1": jwk})))
    claims = {"sub": "user-1", "iss": "https://issuer.example", "aud": "aceit", "exp": int(time.time()) + 600, "email": "a@b.c", "token_use": "id"}
    tok = lambda **over: jwt.encode({**claims, **over}, key, algorithm="RS256", headers={"kid": "k1"})
    ok = lambda t: c.get("/v1/me", headers={"Authorization": f"Bearer {t}"}).status_code
    assert ok(tok()) == 200
    assert ok(tok(exp=int(time.time()) - 5)) == 401                   # expired
    assert ok(tok(iss="https://evil.example")) == 401                 # wrong issuer
    assert ok(tok(aud="other")) == 401                                # wrong audience
    assert ok(tok(token_use="access")) == 401                         # an access token is not accepted where an ID token is required
    assert ok("not.a.token") == 401
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert ok(jwt.encode(claims, other, algorithm="RS256", headers={"kid": "k1"})) == 401     # signed by someone else
    assert ok(jwt.encode(claims, key=None, algorithm="none", headers={"kid": "k1"})) == 401   # 'none' is never accepted
    assert c.get("/v1/me").status_code == 401


def test_dev_mode_is_not_the_default(monkeypatch):
    from aceit.platform.config import load
    monkeypatch.delenv("ACEIT_AUTH_MODE", raising=False)
    assert load().auth_mode == "jwt"


# ---------------------------------------------------------------- topics
def test_free_text_resolves_to_syllabus_topics(client):
    r = client.get("/v1/topics/resolve", params={"q": "DP"}, headers=H()).json()
    assert [m["slug"] for m in r["matches"]] == ["algorithms/algorithm-design-techniques/dynamic-programming"]
    assert client.get("/v1/topics/resolve", params={"q": "banker's algorithm"}, headers=H()).json()["matches"][0]["slug"] == "operating-system/deadlock"
    assert client.get("/v1/topics/resolve", params={"q": "quantum gravity"}, headers=H()).json()["matches"] == []


# ---------------------------------------------------------------- a topic test, start to finish
def test_topic_test_full_flow_and_scoring(client, clock):
    t = new_test(client, kind="topic", topics=["operating-system"], count=12, seed=5)
    assert t["questions"] == 12 and t["rank_eligible"] is False and t["duration_s"] >= 600
    a = start(client, t["id"])
    assert a["remaining_s"] == t["duration_s"] and a["status"] == "in_progress" and len(a["questions"]) == 12

    # a student must never be shown the key, the solution or the extraction internals
    blob = json.dumps(a["questions"])
    for secret in ("answer", "\"key", "solution", "key_type", "extraction"):
        assert secret not in blob
    assert all(set(q) <= {"id", "section", "type", "marks", "stem_md", "options", "image_crops", "display", "position"} for q in a["questions"])

    # synthetic keys: MCQ=A, MSQ=A+B, NAT=1. Answer the first 4 correctly, the next 2 wrongly, leave the rest.
    def right(q): return {"MCQ": {"choice": "A"}, "MSQ": {"choices": ["B", "A"]}, "NAT": {"value": 1}}[q["type"]]
    def wrong(q): return {"MCQ": {"choice": "B"}, "MSQ": {"choices": ["A"]}, "NAT": {"value": 2}}[q["type"]]
    qs = a["questions"]
    items = [{"question_id": q["id"], "response": right(q), "palette_status": "answered", "time_spent_s": 30} for q in qs[:4]] + \
            [{"question_id": q["id"], "response": wrong(q), "palette_status": "answered", "time_spent_s": 20} for q in qs[4:6]]
    clock["now"] = T0 + timedelta(minutes=5)
    r = client.put(f"/v1/attempts/{a['id']}/responses", json={"seq": 1, "items": items}, headers=H())
    assert r.status_code == 200 and r.json()["reason"] == "ok" and r.json()["remaining_s"] == t["duration_s"] - 300
    # a retry of the same batch is acknowledged and changes nothing
    assert client.put(f"/v1/attempts/{a['id']}/responses", json={"seq": 1, "items": items[:1]}, headers=H()).json()["reason"] == "duplicate"

    # resume shows the saved answers and the same deadline
    back = client.get(f"/v1/attempts/{a['id']}", headers=H()).json()
    assert back["deadline_at"] == a["deadline_at"] and len(back["responses"]) == 6

    res = client.post(f"/v1/attempts/{a['id']}/submit", headers=H()).json()
    expected = sum(q["marks"] for q in qs[:4]) - sum(q["marks"] / 3 for q in qs[4:6] if q["type"] == "MCQ")
    assert res["score"] == pytest.approx(expected, abs=0.01)
    assert res["counts"]["correct"] + res["counts"].get("awarded_to_all", 0) >= 4
    assert res["counts"]["unattempted"] == 6 and res["max_score"] == sum(q["marks"] for q in qs)
    assert "operating-system" not in res["by_topic"] or all(k.startswith("operating-system") for k in res["by_topic"])
    # submitting again changes nothing; the result is fetchable; a closed attempt takes no more saves
    assert client.post(f"/v1/attempts/{a['id']}/submit", headers=H()).json() == res
    assert client.get(f"/v1/attempts/{a['id']}/result", headers=H()).json() == res
    assert client.put(f"/v1/attempts/{a['id']}/responses", json={"seq": 9, "items": items[:1]}, headers=H()).status_code == 409


def test_starting_twice_resumes_and_other_users_see_nothing(client):
    t = new_test(client, kind="topic", topics=["databases"], count=5, seed=1)
    a1, a2 = start(client, t["id"]), start(client, t["id"])
    assert a1["id"] == a2["id"] and a1["deadline_at"] == a2["deadline_at"]
    assert client.get(f"/v1/attempts/{a1['id']}", headers=H("mallory")).status_code == 404
    assert client.post(f"/v1/attempts/{a1['id']}/submit", headers=H("mallory")).status_code == 404
    assert client.get(f"/v1/tests/{t['id']}", headers=H("mallory")).status_code == 404
    assert client.get(f"/v1/attempts/{a1['id']}/result", headers=H()).status_code == 409        # not finished yet


def test_autosave_rules(client, clock):
    t = new_test(client, kind="topic", topics=["algorithms"], count=5, seed=2)
    a = start(client, t["id"])
    qid = a["questions"][0]["id"]
    put = lambda seq, items, now=None: client.put(f"/v1/attempts/{a['id']}/responses", json={"seq": seq, "items": items}, headers=H())
    assert put(1, [{"question_id": "00000000-0000-0000-0000-000000000000"}]).status_code == 422      # not in this test
    assert put(1, [{"question_id": "not-a-uuid"}]).status_code == 422
    assert put(1, [{"question_id": qid, "palette_status": "hacked"}]).status_code == 422
    assert put(1, [{"question_id": qid, "response": {"x": "y" * 600}}]).status_code == 422             # oversized response
    assert put(-1, []).status_code == 422
    assert put(1, [{"question_id": qid, "response": {"choice": "A"}, "palette_status": "answered"}]).status_code == 200
    clock["now"] = T0 + timedelta(seconds=t["duration_s"] + 31)                                       # past the grace period
    assert put(2, [{"question_id": qid, "response": {"choice": "B"}}]).status_code == 409


def test_sweeper_closes_abandoned_attempts_and_scores_them(client, pool, clock):
    t = new_test(client, kind="topic", topics=["theory-of-computation"], count=5, seed=3)
    a = start(client, t["id"])
    q = a["questions"][0]
    right = {"MCQ": {"choice": "A"}, "MSQ": {"choices": ["A", "B"]}, "NAT": {"value": 1}}[q["type"]]
    client.put(f"/v1/attempts/{a['id']}/responses", json={"seq": 1, "items": [{"question_id": q["id"], "response": right, "palette_status": "answered"}]}, headers=H())
    now = T0 + timedelta(seconds=t["duration_s"] + 31)
    with pool.connection() as conn:
        assert store.sweep_expired(conn, now) >= 1
        assert store.sweep_expired(conn, now) == 0                                                    # nothing left to close
    clock["now"] = now
    res = client.get(f"/v1/attempts/{a['id']}/result", headers=H()).json()
    assert res["score"] >= q["marks"] and res["rank_eligible"] is False
    with pool.connection() as conn:
        assert conn.execute("SELECT status, submitted_at FROM attempt WHERE id = %s::uuid", (a["id"],)).fetchone() == {"status": "auto_submitted", "submitted_at": T0 + timedelta(seconds=t["duration_s"])}


# ---------------------------------------------------------------- a full mock
def test_full_mock_follows_the_blueprint(client):
    t = new_test(client, kind="full", seed=11)
    assert t["questions"] == 65 and t["duration_s"] == 10800
    a = start(client, t["id"])
    qs = a["questions"]
    assert [q["section"] for q in qs[:10]] == ["GA"] * 10 and sum(q["marks"] for q in qs) == 100
    assert len({q["id"] for q in qs}) == 65
    # the same seed gives the same test, a student's next test avoids what they already saw
    assert new_test(client, "bob", kind="full", seed=11)["questions"] == 65
    second = start(client, new_test(client, kind="full", seed=12)["id"])
    assert len({q["id"] for q in qs} & {q["id"] for q in second["questions"]}) == 0


def test_rank_only_full_mock_fails_loudly_when_the_pool_is_too_small(client):
    r = client.post("/v1/tests", json={"kind": "full", "rank_only": True, "seed": 1}, headers=H("carol"))
    assert r.status_code in (201, 422)                       # 2018+ rank-eligible pool = 2024 only (130 questions)
    if r.status_code == 201:
        assert r.json()["rank_eligible"] is True


def test_bad_requests(client):
    assert client.post("/v1/tests", json={"kind": "topic"}, headers=H()).status_code == 422                       # no topics
    assert client.post("/v1/tests", json={"kind": "topic", "topics": ["no-such-topic"]}, headers=H()).status_code == 422
    assert client.post("/v1/tests", json={"kind": "weird"}, headers=H()).status_code == 422
    assert client.post("/v1/tests", json={"kind": "topic", "topics": ["databases"], "count": 500}, headers=H()).status_code == 422
    assert client.post("/v1/attempts", json={"test_id": "not-a-uuid"}, headers=H()).status_code == 422
    assert client.post("/v1/attempts", json={}, headers=H()).status_code == 422
    assert client.post("/v1/attempts", json={"test_id": "00000000-0000-0000-0000-000000000000"}, headers=H()).status_code == 404
    assert client.get("/v1/attempts/not-a-uuid", headers=H()).status_code == 422
    assert client.put("/v1/attempts/00000000-0000-0000-0000-000000000000/responses", json={"seq": 1, "items": []}, headers=H()).status_code == 404


# ---------------------------------------------------------------- web app support: config, history, review, images
def test_config_is_public_and_says_how_to_sign_in(client):
    assert client.get("/v1/config").json() == {"auth_mode": "dev", "cognito": None}


def test_history_and_review_only_after_submission(client, pool, clock):
    t = new_test(client, "dave", kind="topic", topics=["databases"], count=6, seed=9)
    a = start(client, t["id"], "dave")
    assert [x["status"] for x in client.get("/v1/attempts", headers=H("dave")).json()] == ["in_progress"]
    # the official answers are NOT available while the test is running
    assert client.get(f"/v1/attempts/{a['id']}/review", headers=H("dave")).status_code == 409
    q0 = a["questions"][0]
    right = {"MCQ": {"choice": "A"}, "MSQ": {"choices": ["A", "B"]}, "NAT": {"value": 1}}[q0["type"]]
    client.put(f"/v1/attempts/{a['id']}/responses", json={"seq": 1, "items": [{"question_id": q0["id"], "response": right, "palette_status": "answered"}]}, headers=H("dave"))
    res = client.post(f"/v1/attempts/{a['id']}/submit", headers=H("dave")).json()

    rev = client.get(f"/v1/attempts/{a['id']}/review", headers=H("dave")).json()
    assert len(rev) == 6 and [r["position"] for r in rev] == [1, 2, 3, 4, 5, 6]
    assert rev[0]["outcome"] in ("correct", "awarded_to_all") and rev[0]["response"] == right and rev[0]["key_type"] in ("mcq", "msq", "nat", "mta")
    assert sum(r["marks_awarded"] for r in rev) == pytest.approx(res["score"], abs=0.01)         # the review adds up to the score
    assert all(r["outcome"] == "unattempted" for r in rev[1:] if r["key_type"] not in ("mta", "dropped"))
    hist = client.get("/v1/attempts", headers=H("dave")).json()
    assert hist[0]["status"] == "submitted" and hist[0]["score"] == res["score"] and hist[0]["questions"] == 6
    assert client.get(f"/v1/attempts/{a['id']}/review", headers=H("erin")).status_code == 404     # someone else's attempt
    assert client.get("/v1/attempts", headers=H("erin")).json() == []                               # and not in their history


def test_question_images_are_served_only_to_people_with_the_test_and_never_outside_the_folder(client, pool, tmp_path, monkeypatch):
    crops = tmp_path / "ingest"; (crops / "2024_CS1").mkdir(parents=True)
    (crops / "2024_CS1" / "Q01_1.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "secret.txt").write_text("do not serve")
    t = new_test(client, "frank", kind="topic", topics=["databases"], count=3, seed=4)
    a = start(client, t["id"], "frank")
    vid = a["questions"][0]["id"]
    def set_fig(path):                                        # versions are immutable by design: bypass the trigger for this fixture only
        with pool.connection() as conn:
            conn.execute("SET LOCAL session_replication_role = replica")
            conn.execute("UPDATE question_version SET figures = %s::jsonb WHERE id = %s::uuid", (json.dumps([{"path": path}] if path else []), vid))
    url = f"/v1/questions/{vid}/images/0"
    try:
        monkeypatch.delenv("ACEIT_CROPS_DIR", raising=False)
        set_fig("ingest/2024_CS1/Q01_1.png")
        assert client.get(url, headers=H("frank")).status_code == 404                              # no folder configured
        monkeypatch.setenv("ACEIT_CROPS_DIR", str(crops))
        r = client.get(url, headers=H("frank"))
        assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content.startswith(b"\x89PNG")
        assert client.get(url, headers=H("grace")).status_code == 404                              # grace has no test with this question
        assert client.get(f"/v1/questions/{vid}/images/5", headers=H("frank")).status_code == 404  # no such crop
        set_fig("ingest/../secret.txt")                                                            # a stored path must not escape
        assert client.get(url, headers=H("frank")).status_code == 404
        set_fig("ingest/2024_CS1/missing.png")
        assert client.get(url, headers=H("frank")).status_code == 404
    finally:
        set_fig(None)


def test_analysis_after_submit_and_progress(client, clock):
    t = new_test(client, user="dana", kind="topic", topics=["operating-system"], count=10, seed=9)
    a = start(client, t["id"], "dana")
    assert client.get(f"/v1/attempts/{a['id']}/analysis", headers=H("dana")).status_code == 409        # nothing before the test is over
    qs = a["questions"]
    wrong = {"MCQ": {"choice": "B"}, "MSQ": {"choices": ["A"]}, "NAT": {"value": 2}}
    items = [{"question_id": q["id"], "response": wrong[q["type"]], "palette_status": "answered", "time_spent_s": 10} for q in qs[:4]]
    client.put(f"/v1/attempts/{a['id']}/responses", json={"seq": 1, "items": items}, headers=H("dana"))
    client.post(f"/v1/attempts/{a['id']}/submit", headers=H("dana"))
    r = client.get(f"/v1/attempts/{a['id']}/analysis", headers=H("dana"))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["marks"]["possible"] == sum(q["marks"] for q in qs) and out["marks"]["unattempted_questions"] == 6
    assert out["topics"] and out["cohort"] is None                                                       # topic tests carry no rank
    assert any(i["kind"] == "weak" for i in out["insights"])
    assert client.get(f"/v1/attempts/{a['id']}/analysis", headers=H("erin")).status_code == 404       # someone else's attempt
    p = client.get("/v1/me/progress", headers=H("dana")).json()
    assert p["predicted"] is None and p["subjects"]["operating-system"]["questions"] == 10             # too little evidence to predict


def test_production_auth_refuses_to_start_unchecked_and_cognito_settings_follow_from_the_pool(monkeypatch, pool):
    from aceit.platform.config import load
    with pytest.raises(RuntimeError):
        create_app(Settings("x", "jwt"), pool)                                                  # no issuer/audience: would accept any issuer
    for k, v in dict(ACEIT_AUTH_MODE="jwt", ACEIT_COGNITO_REGION="ap-south-1", ACEIT_COGNITO_POOL_ID="ap-south-1_AbC123", ACEIT_COGNITO_CLIENT_ID="client123",
                     ACEIT_COGNITO_DOMAIN="https://aceit.auth.ap-south-1.amazoncognito.com/").items():
        monkeypatch.setenv(k, v)
    s = load()
    assert s.jwt_issuer == "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_AbC123" and s.jwt_audience == "client123" and s.jwt_token_use == "id"
    assert s.jwks_url == s.jwt_issuer + "/.well-known/jwks.json" and s.cognito_domain == "aceit.auth.ap-south-1.amazoncognito.com"
    cfg = TestClient(create_app(s, pool, jwks=JwksCache(keys={}))).get("/v1/config").json()
    assert cfg == {"auth_mode": "jwt", "cognito": {"domain": "aceit.auth.ap-south-1.amazoncognito.com", "client_id": "client123"}}


def answer_all(client, a, user, right):
    """Answer every question in an attempt: right=True gives the synthetic key, False a wrong answer."""
    good = {"MCQ": {"choice": "A"}, "MSQ": {"choices": ["A", "B"]}, "NAT": {"value": 1}}
    bad = {"MCQ": {"choice": "B"}, "MSQ": {"choices": ["A"]}, "NAT": {"value": 2}}
    items = [{"question_id": q["id"], "response": (good if right else bad)[q["type"]], "palette_status": "answered", "time_spent_s": 20} for q in a["questions"]]
    assert client.put(f"/v1/attempts/{a['id']}/responses", json={"seq": 1, "items": items}, headers=H(user)).status_code == 200
    return client.post(f"/v1/attempts/{a['id']}/submit", headers=H(user)).json()


def test_mistakes_notebook_retry_and_comparison_with_the_previous_attempt(client, clock):
    u = "retryer"
    assert client.get("/v1/me/mistakes", headers=H(u)).json() == {"count": 0, "topics": []}
    assert client.post("/v1/tests", json={"kind": "retry"}, headers=H(u)).status_code == 422          # nothing to retry yet
    t = new_test(client, user=u, kind="topic", topics=["operating-system"], count=8, seed=31)
    a = start(client, t["id"], u)
    answer_all(client, a, u, right=False)
    m = client.get("/v1/me/mistakes", headers=H(u)).json()
    wrong_mcq_msq = sum(1 for q in a["questions"])                                                  # every answer was wrong (NAT 2 is outside 1..1)
    assert m["count"] == wrong_mcq_msq and m["topics"][0]["count"] >= 1
    # retry them, this time correctly: they leave the notebook by themselves
    r = client.post("/v1/tests", json={"kind": "retry", "count": 5}, headers=H(u))
    assert r.status_code == 201 and r.json()["questions"] == 5 and r.json()["rank_eligible"] is False
    clock["now"] += timedelta(hours=1)                                                              # later attempts start later
    b = start(client, r.json()["id"], u)
    res = answer_all(client, b, u, right=True)
    assert res["counts"].get("wrong", 0) == 0
    assert client.get("/v1/me/mistakes", headers=H(u)).json()["count"] == m["count"] - 5
    # the second attempt is compared with the first one of its own kind ("custom"): none yet; the first topic test has no earlier one either
    assert client.get(f"/v1/attempts/{a['id']}/analysis", headers=H(u)).json()["vs_previous"] is None
    clock["now"] += timedelta(hours=1)
    t2 = new_test(client, user=u, kind="topic", topics=["operating-system"], count=8, seed=32)
    a2 = start(client, t2["id"], u)
    answer_all(client, a2, u, right=True)
    v = client.get(f"/v1/attempts/{a2['id']}/analysis", headers=H(u)).json()["vs_previous"]
    assert v["previous_attempt_id"] == a["id"] and v["percent_now"] > v["percent_before"] and v["change"] == pytest.approx(v["percent_now"] - v["percent_before"], abs=0.11)
    # the analysis explains the lost marks, and the review carries a difficulty field (None until enough students have tried it)
    an = client.get(f"/v1/attempts/{a['id']}/analysis", headers=H(u)).json()
    assert an["why"] and {p["reason"] for p in an["per_question"]} <= {"silly", "careless", "slow", "concept", "skipped", "not_reached"}
    rv = client.get(f"/v1/attempts/{a['id']}/review", headers=H(u)).json()
    assert all("difficulty" in q for q in rv) and all(q["difficulty"] is None for q in rv)


def test_past_papers_can_be_sat_exactly_as_set(client):
    ps = client.get("/v1/papers", headers=H("pyqer")).json()
    assert ps and all(p["questions"] == 65 for p in ps)
    p = ps[0]
    r = client.post("/v1/tests", json={"kind": "pyq", "year": p["year"], "sitting": p["sitting"]}, headers=H("pyqer"))
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["kind"] == "pyq" and t["questions"] == 65 and t["duration_s"] == 10800 and t["rank_eligible"] == p["rank_eligible"]
    a = start(client, t["id"], "pyqer")
    nums = [q["position"] for q in a["questions"]]
    assert nums == list(range(1, 66))
    assert client.post("/v1/tests", json={"kind": "pyq", "year": 1999, "sitting": "CS"}, headers=H("pyqer")).status_code == 422
    assert client.post("/v1/tests", json={"kind": "pyq"}, headers=H("pyqer")).status_code == 422


def test_bookmarks_and_private_notes(client):
    u = "noter"
    t = new_test(client, user=u, kind="topic", topics=["operating-system"], count=6, seed=61)
    a = start(client, t["id"], u)
    vid = a["questions"][0]["id"]
    assert client.put(f"/v1/questions/{vid}/note", json={"bookmarked": True}, headers=H(u)).status_code == 404          # not until the test is over
    client.post(f"/v1/attempts/{a['id']}/submit", headers=H(u))
    r = client.put(f"/v1/questions/{vid}/note", json={"bookmarked": True}, headers=H(u))
    assert r.status_code == 200 and r.json() == {"bookmarked": True, "note": ""}
    r = client.put(f"/v1/questions/{vid}/note", json={"note": "remember: cycle in the wait-for graph"}, headers=H(u))
    assert r.json() == {"bookmarked": True, "note": "remember: cycle in the wait-for graph"}                            # a partial update keeps the other field
    assert client.put(f"/v1/questions/{vid}/note", json={"note": "x" * 2001}, headers=H(u)).status_code == 422
    rv = client.get(f"/v1/attempts/{a['id']}/review", headers=H(u)).json()
    assert rv[0]["bookmarked"] is True and rv[0]["note"].startswith("remember") and rv[1]["bookmarked"] is False and rv[1]["note"] == ""
    b = client.get("/v1/me/bookmarks", headers=H(u)).json()
    assert b["count"] == 1 and b["items"][0]["version_id"] == vid and b["items"][0]["topic"]
    # practise the bookmarks like a retry test
    p = client.post("/v1/tests", json={"kind": "retry", "source": "bookmarks"}, headers=H(u))
    assert p.status_code == 201 and p.json()["questions"] == 1
    # notes are private: another student can neither write to nor read them
    assert client.put(f"/v1/questions/{vid}/note", json={"note": "hijack"}, headers=H("snoop")).status_code == 404
    assert client.get("/v1/me/bookmarks", headers=H("snoop")).json() == {"count": 0, "items": []}
    assert client.post("/v1/tests", json={"kind": "retry", "source": "bookmarks"}, headers=H("snoop")).status_code == 422
    # un-bookmarking removes it but keeps the note
    assert client.put(f"/v1/questions/{vid}/note", json={"bookmarked": False}, headers=H(u)).json()["note"].startswith("remember")
    assert client.get("/v1/me/bookmarks", headers=H(u)).json()["count"] == 0


def test_a_student_can_export_and_erase_their_own_data(client, pool):
    t = new_test(client, "leaver", kind="topic", topics=["operating-system"], count=6, seed=71)
    a = start(client, t["id"], "leaver")
    q = a["questions"][0]
    client.put(f"/v1/attempts/{a['id']}/responses", json={"seq": 1, "items": [{"question_id": q["id"], "response": {"choice": "A"}, "palette_status": "answered", "time_spent_s": 9}]}, headers=H("leaver"))
    client.post(f"/v1/attempts/{a['id']}/submit", headers=H("leaver"))
    client.put(f"/v1/questions/{a['questions'][0]['id']}/note", json={"note": "mine"}, headers=H("leaver"))
    new_test(client, "stayer", kind="topic", topics=["operating-system"], count=6, seed=72)
    d = client.get("/v1/me/export", headers=H("leaver"))
    assert d.status_code == 200 and "attachment" in d.headers["content-disposition"]
    body = d.json()
    assert len(body["attempts"]) == 1 and body["attempts"][0]["responses"] and body["notes"][0]["note"] == "mine"
    assert client.delete("/v1/me", headers=H("leaver")).status_code == 204
    n = lambda sql: pool.connection().__enter__().execute(sql).fetchone()["n"]
    assert n("SELECT count(*) n FROM app_user WHERE cognito_sub = 'leaver'") == 0
    assert n("SELECT count(*) n FROM attempt WHERE id = '%s'" % a["id"]) == 0
    assert n("SELECT count(*) n FROM attempt_response WHERE attempt_id = '%s'" % a["id"]) == 0
    assert client.get("/v1/me/export", headers=H("stayer")).json()["profile"]["id"]      # someone else is untouched


def test_username_is_chosen_once_unique_ignoring_case_and_validated(client):
    assert client.get("/v1/me", headers=H("nameless")).json()["username"] is None
    assert client.put("/v1/me/username", json={"username": "Ace_77"}, headers=H("nameless")).status_code == 200
    assert client.get("/v1/me", headers=H("nameless")).json()["username"] == "Ace_77"
    assert client.put("/v1/me/username", json={"username": "ace_77"}, headers=H("other")).status_code == 409      # taken, ignoring case
    assert client.put("/v1/me/username", json={"username": "Ace_77"}, headers=H("nameless")).status_code == 200    # your own name again is fine
    for bad in ("ab", "x" * 21, "has space", "a@b.com", "emoji😀name"):
        assert client.put("/v1/me/username", json={"username": bad}, headers=H("other")).status_code == 422
