"""SQL for the exam flow. Every function takes an open psycopg connection (rows are dicts) and does one job."""
import re
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from aceit.analytics.analysis import difficulty_label
from aceit.scoring.attempt import Item, score_attempt
from aceit.session.attempt import Attempt, Response, submit as engine_submit
from aceit.testing.assembler import Candidate


def upsert_user(conn, sub: str, email: str | None) -> str:
    return conn.execute(
        "INSERT INTO app_user (cognito_sub, email) VALUES (%s, %s) ON CONFLICT (cognito_sub) DO UPDATE SET email = COALESCE(EXCLUDED.email, app_user.email) RETURNING id::text",
        (sub, email)).fetchone()["id"]


def get_username(conn, user_id: str) -> str | None:
    return conn.execute("SELECT username FROM app_user WHERE id = %s::uuid", (user_id,)).fetchone()["username"]


def set_username(conn, user_id: str, username: str) -> bool:
    """False when someone else already has it (compared ignoring case)."""
    try:
        conn.execute("UPDATE app_user SET username = %s WHERE id = %s::uuid", (username, user_id))
        return True
    except psycopg.errors.UniqueViolation:
        return False


def export_user(conn, user_id: str) -> dict:
    """Everything we hold about one student, as plain data: profile, every attempt with their answers, notes and bookmarks."""
    me = conn.execute("SELECT id::text, email, username, role, created_at FROM app_user WHERE id = %s::uuid", (user_id,)).fetchone()
    attempts = conn.execute(
        "SELECT a.id::text, a.status, a.started_at, a.submitted_at, a.score, a.result, ti.kind FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id "
        "WHERE a.user_id = %s::uuid ORDER BY a.started_at", (user_id,)).fetchall()
    for a in attempts:
        a["responses"] = conn.execute(
            "SELECT question_version_id::text, response, palette_status, time_spent_s, is_correct, marks_awarded FROM attempt_response WHERE attempt_id = %s::uuid", (a["id"],)).fetchall()
    notes = conn.execute("SELECT question_id::text, bookmarked, note, updated_at FROM question_note WHERE user_id = %s::uuid", (user_id,)).fetchall()
    return {"profile": me, "attempts": attempts, "notes": notes}


def delete_user(conn, user_id: str) -> None:
    """Erases the student. Their tests, attempts, answers and notes go with them (ON DELETE CASCADE); question reports stay but lose the reporter."""
    conn.execute("DELETE FROM app_user WHERE id = %s::uuid", (user_id,))


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9+]+", " ", s.lower()).split())


def resolve_topic(conn, text: str) -> list[dict]:
    """Free text -> syllabus topics. Exact match on the normalised alias table (design §20.1, first step)."""
    return conn.execute(
        "SELECT t.slug, t.name, t.level FROM topic_alias a JOIN topic t ON t.id = a.topic_id WHERE a.alias = %s ORDER BY t.level, t.slug",
        (norm(text),)).fetchall()


def load_pool(conn, min_year: int | None = None) -> list[Candidate]:
    """Questions a student may be given: live, public, keyed, from a live sitting (view v_servable_question)."""
    rows = conn.execute(
        """SELECT s.version_id::text AS id, s.section, s.marks, s.q_type, s.rank_eligible,
                  split_part(t.slug, '/', 1) AS subject, t.slug AS topic
           FROM v_servable_question s
           JOIN question_topic qt ON qt.question_id = s.question_id AND qt.is_primary
           JOIN topic t ON t.id = qt.topic_id
           LEFT JOIN paper_session ps ON ps.id = s.session_id
           WHERE (%s::int IS NULL OR ps.year >= %s::int)""", (min_year, min_year)).fetchall()
    return [Candidate(r["id"], r["section"], r["marks"], r["q_type"], r["subject"], r["topic"], "", r["rank_eligible"]) for r in rows]


def seen_versions(conn, user_id: str) -> set[str]:
    rows = conn.execute("SELECT DISTINCT unnest(ti.question_version_ids)::text AS v FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id WHERE a.user_id = %s", (user_id,)).fetchall()
    return {r["v"] for r in rows}


def create_test(conn, owner_id: str | None, kind: str, seed: int, version_ids: list[str], duration_s: int, rank_eligible: bool, blueprint: str | None, shelf_key: str | None = None, pair_id: str | None = None, pair_set: int | None = None) -> str:
    return conn.execute(
        """INSERT INTO test_instance (paper_id, kind, seed, blueprint_version, question_version_ids, duration_s, rank_eligible, owner_id, shelf_key, pair_id, pair_set)
           SELECT p.id, %s, %s, %s, %s::uuid[], %s, %s, %s::uuid, %s, %s::uuid, %s FROM paper p WHERE p.code = 'CS' RETURNING id::text""",
        (kind, seed, blueprint, version_ids, duration_s, rank_eligible, owner_id, shelf_key, pair_id, pair_set)).fetchone()["id"]


def pick_shelf_pair(conn, keys: list[str], seen: set[str]) -> list[dict] | None:
    """A shelf pair of which the student has not met a single question in either set (first key wins), or None."""
    row = conn.execute(
        """SELECT pair_id::text FROM test_instance WHERE shelf_key = ANY(%s) AND pair_id IS NOT NULL GROUP BY pair_id, shelf_key
           HAVING NOT bool_or(question_version_ids && %s::uuid[]) ORDER BY array_position(%s::text[], shelf_key), random() LIMIT 1""", (keys, list(seen), keys)).fetchone()
    return pair_sets(conn, row["pair_id"]) if row else None


def pair_sets(conn, pair_id: str) -> list[dict]:
    return conn.execute("SELECT id::text, pair_id::text, pair_set AS set, cardinality(question_version_ids) AS questions, duration_s, rank_eligible, seed FROM test_instance WHERE pair_id = %s::uuid ORDER BY pair_set", (pair_id,)).fetchall()


def pair_status(conn, pair_id: str, user_id: str) -> list[dict]:
    """The sets of a pair this student may use, each with their latest attempt on it (if any)."""
    return conn.execute(
        """SELECT ti.id::text AS test_id, ti.pair_set AS set, ti.duration_s, a.id::text AS attempt_id, a.status, (a.result->>'score')::float AS score, (a.result->>'max_score')::float AS max_score
           FROM test_instance ti LEFT JOIN LATERAL (SELECT * FROM attempt x WHERE x.test_instance_id = ti.id AND x.user_id = %s::uuid ORDER BY x.started_at DESC LIMIT 1) a ON true
           WHERE ti.pair_id = %s::uuid AND (ti.owner_id IS NULL OR ti.owner_id = %s::uuid) ORDER BY ti.pair_set""", (user_id, pair_id, user_id)).fetchall()


def pick_shelf(conn, keys: list[str], seen: set[str]) -> dict | None:
    """A shelf test the student has not met a single question of (first key in the list wins), or None."""
    return conn.execute(
        """SELECT id::text, kind, question_version_ids::text[] AS version_ids, duration_s, rank_eligible, seed FROM test_instance
           WHERE shelf_key = ANY(%s) AND NOT (question_version_ids && %s::uuid[])
           ORDER BY array_position(%s::text[], shelf_key), random() LIMIT 1""", (keys, list(seen), keys)).fetchone()


def get_test(conn, test_id: str, user_id: str) -> dict | None:
    return conn.execute(
        "SELECT id::text, kind, seed, blueprint_version, question_version_ids::text[] AS version_ids, duration_s, rank_eligible FROM test_instance WHERE id = %s::uuid AND (owner_id IS NULL OR owner_id = %s::uuid)",
        (test_id, user_id)).fetchone()


def question_payload(conn, version_ids: list[str]) -> list[dict]:
    """What a student may see while the test runs. NEVER includes the key or the solution."""
    rows = conn.execute(
        """SELECT v.id::text AS id, q.section, q.q_type AS type, q.marks, qv.stem_md, qv.options,
                  jsonb_array_length(qv.figures) AS image_crops, qv.extraction->>'display' AS display
           FROM unnest(%s::uuid[]) WITH ORDINALITY AS v(id, ord)
           JOIN question_version qv ON qv.id = v.id JOIN question q ON q.id = qv.question_id ORDER BY v.ord""", (version_ids,)).fetchall()
    for i, r in enumerate(rows, 1):
        r["position"] = i
    return rows


def create_attempt(conn, test_id: str, user_id: str, started_at: datetime, deadline_at: datetime) -> str:
    return conn.execute("INSERT INTO attempt (test_instance_id, user_id, started_at, deadline_at) VALUES (%s::uuid, %s::uuid, %s, %s) RETURNING id::text",
                        (test_id, user_id, started_at, deadline_at)).fetchone()["id"]


def lock_attempt(conn, attempt_id: str, user_id: str) -> dict | None:
    return conn.execute(
        """SELECT a.id::text, a.user_id::text, a.started_at, a.deadline_at, a.status, a.submitted_at, a.last_seq, a.result, a.integrity,
                  ti.question_version_ids::text[] AS version_ids, ti.duration_s, ti.rank_eligible, ti.kind, ti.blueprint_version
           FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id
           WHERE a.id = %s::uuid AND a.user_id = %s::uuid FOR UPDATE OF a""", (attempt_id, user_id)).fetchone()


def engine_attempt(conn, row: dict) -> Attempt:
    a = Attempt(row["id"], row["user_id"], row["started_at"], row["deadline_at"], row["status"], row["submitted_at"], row["last_seq"])
    a.integrity.update(row["integrity"] or {})
    for r in conn.execute("SELECT question_version_id::text AS q, response, palette_status, time_spent_s FROM attempt_response WHERE attempt_id = %s::uuid", (row["id"],)):
        a.responses[r["q"]] = Response(r["response"], r["palette_status"], r["time_spent_s"])
    return a


def save_responses(conn, attempt_id: str, a: Attempt, touched: set[str], now: datetime) -> None:
    for q in touched:
        r = a.responses[q]
        conn.execute(
            """INSERT INTO attempt_response (attempt_id, question_version_id, response, palette_status, time_spent_s, updated_at)
               VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)
               ON CONFLICT (attempt_id, question_version_id) DO UPDATE SET response = EXCLUDED.response,
                   palette_status = EXCLUDED.palette_status, time_spent_s = EXCLUDED.time_spent_s, updated_at = EXCLUDED.updated_at""",
            (attempt_id, q, Jsonb(r.response) if r.response is not None else None, r.palette_status, r.time_spent_s, now))
    conn.execute("UPDATE attempt SET last_seq = %s WHERE id = %s::uuid", (a.last_seq, attempt_id))


def scoring_items(conn, attempt_id: str, version_ids: list[str]) -> list[Item]:
    rows = conn.execute(
        """SELECT v.id::text AS qid, q.section, q.q_type, q.marks, k.key_type, k.answer, t.slug AS topic, r.response, COALESCE(r.time_spent_s, 0) AS spent
           FROM unnest(%s::uuid[]) WITH ORDINALITY AS v(id, ord)
           JOIN question_version qv ON qv.id = v.id JOIN question q ON q.id = qv.question_id
           JOIN question_key k ON k.question_version_id = qv.id AND k.is_current
           LEFT JOIN question_topic qt ON qt.question_id = q.id AND qt.is_primary
           LEFT JOIN topic t ON t.id = qt.topic_id
           LEFT JOIN attempt_response r ON r.attempt_id = %s::uuid AND r.question_version_id = qv.id
           ORDER BY v.ord""", (version_ids, attempt_id)).fetchall()
    return [Item(r["qid"], r["section"], r["q_type"], r["marks"], r["key_type"], r["answer"], r["topic"], r["response"], r["spent"]) for r in rows]


def finish_attempt(conn, row: dict, now: datetime, forced: bool = False) -> dict:
    """Close an attempt (student submit, or the sweeper with forced=True) and score it ONCE. Idempotent."""
    if row["status"] != "in_progress":
        return row["result"]
    a = engine_attempt(conn, row)
    if forced:
        a.status, a.submitted_at = "auto_submitted", a.deadline_at
    else:
        engine_submit(a, now)
    res = score_attempt(scoring_items(conn, row["id"], row["version_ids"]))
    result = res.as_json()
    result["rank_eligible"] = bool(row["rank_eligible"]) and a.status == "submitted"
    conn.execute("UPDATE attempt SET status = %s, submitted_at = %s, score = %s, section_scores = %s, result = %s WHERE id = %s::uuid",
                 (a.status, a.submitted_at, result["score"], Jsonb(result["by_section"]), Jsonb(result), row["id"]))
    return result


def sweep_expired(conn, now: datetime, grace_s: int = 30) -> int:
    """The safety net: close attempts abandoned past deadline + grace. Returns how many were closed."""
    rows = conn.execute(
        """SELECT a.id::text, a.user_id::text, a.started_at, a.deadline_at, a.status, a.submitted_at, a.last_seq, a.result, a.integrity,
                  ti.question_version_ids::text[] AS version_ids, ti.duration_s, ti.rank_eligible
           FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id
           WHERE a.status = 'in_progress' AND a.deadline_at + make_interval(secs => %s) < %s FOR UPDATE OF a SKIP LOCKED""", (grace_s, now)).fetchall()
    for r in rows:
        finish_attempt(conn, r, now, forced=True)
    return len(rows)


def list_attempts(conn, user_id: str, limit: int = 20) -> list[dict]:
    return conn.execute(
        """SELECT a.id::text, a.status, a.started_at, a.deadline_at, a.submitted_at, ti.kind, ti.pair_id::text, ti.pair_set, cardinality(ti.question_version_ids) AS questions,
                  (a.result->>'score')::float AS score, (a.result->>'max_score')::float AS max_score,
                  (a.result->'counts'->>'correct')::int AS correct, (a.result->'counts'->>'wrong')::int AS wrong
           FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id
           WHERE a.user_id = %s::uuid ORDER BY a.started_at DESC LIMIT %s""", (user_id, limit)).fetchall()


def review(conn, attempt_id: str, version_ids: list[str]) -> list[dict]:
    """After submission only: every question with the student's answer, the official key and the outcome."""
    payload = {p["id"]: p for p in question_payload(conn, version_ids)}
    items = scoring_items(conn, attempt_id, version_ids)
    res = score_attempt(items)
    out = []
    for it, (qid, o) in zip(items, res.per_question):
        p = payload[qid]
        out.append({**p, "response": it.response, "key_type": it.key_type, "key": it.key, "topic": it.topic,
                    "outcome": o.status, "marks_awarded": round(float(o.marks), 2), "time_spent_s": it.time_spent_s})
    stats = {r["v"]: r for r in conn.execute("SELECT qv.id::text AS v, s.correct_rate, s.attempts FROM question_version qv JOIN question_stats s ON s.question_id = qv.question_id "
                                             "WHERE qv.id = ANY(%s::uuid[])", (version_ids,)).fetchall()}
    sol = {r["v"]: r["solution_md"] for r in conn.execute("SELECT id::text AS v, solution_md FROM question_version WHERE id = ANY(%s::uuid[])", (version_ids,)).fetchall()}
    for r in out:
        r["explanation"] = sol.get(r["id"])               # AI-written and checked against the official answer; only ever returned after the test is over
    for r in out:                                         # how hard other students found it, once enough of them have tried it
        st = stats.get(r["id"])
        r["difficulty"] = difficulty_label(st["correct_rate"], st["attempts"]) if st else None
        r["correct_rate"] = round(st["correct_rate"], 2) if st and r["difficulty"] else None
    return out


def cohort_scores(conn, user_id: str, blueprint_version: str) -> list[float]:
    """Best score of every OTHER student on rank-bearing full mocks of the same blueprint (scores are out of the same 100)."""
    rows = conn.execute(
        """SELECT max(a.score)::float AS s FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id
           WHERE a.status = 'submitted' AND (a.result->>'rank_eligible')::boolean AND ti.blueprint_version = %s AND a.user_id <> %s::uuid
           GROUP BY a.user_id""", (blueprint_version, user_id)).fetchall()
    return [r["s"] for r in rows]


def subject_stats(conn, user_id: str, limit: int = 30) -> dict:
    """Marks earned / possible and question count per subject over the student's last finished attempts."""
    out: dict[str, dict] = {}
    for a in conn.execute("SELECT a.id::text, ti.question_version_ids::text[] AS v FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id "
                          "WHERE a.user_id = %s::uuid AND a.status <> 'in_progress' ORDER BY a.started_at DESC LIMIT %s", (user_id, limit)).fetchall():
        for r in review(conn, a["id"], a["v"]):
            if r["outcome"] in ("not_scored",):
                continue
            s = out.setdefault((r["topic"] or "unknown").split("/")[0], {"earned": 0.0, "possible": 0.0, "questions": 0})
            s["earned"] += r["marks_awarded"]; s["possible"] += r["marks"]; s["questions"] += 1
    return out


def figure_path(conn, user_id: str, version_id: str, n: int) -> str | None:
    """Path of crop n of a question, but only if the user has a test containing that question."""
    row = conn.execute(
        """SELECT qv.figures -> %s ->> 'path' AS path FROM question_version qv
           WHERE qv.id = %s::uuid AND EXISTS (SELECT 1 FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id
                                              WHERE a.user_id = %s::uuid AND %s::uuid = ANY(ti.question_version_ids))""",
        (n, version_id, user_id, version_id)).fetchone()
    return row["path"] if row else None


def previous_attempt(conn, user_id: str, attempt_id: str, kind: str) -> dict | None:
    """The student's previous finished attempt of the same kind of test, for "how did I do compared with last time"."""
    return conn.execute(
        """SELECT a.id::text, (a.result->>'score')::float AS score, (a.result->>'max_score')::float AS max_score,
                  (a.result->'counts'->>'correct')::int AS correct, (a.result->'counts'->>'wrong')::int AS wrong, (a.result->'counts'->>'unattempted')::int AS unattempted
           FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id
           WHERE a.user_id = %s::uuid AND a.id <> %s::uuid AND a.status IN ('submitted', 'auto_submitted') AND ti.kind = %s
             AND a.started_at < (SELECT started_at FROM attempt WHERE id = %s::uuid) ORDER BY a.started_at DESC LIMIT 1""",
        (user_id, attempt_id, kind, attempt_id)).fetchone()


def mistakes(conn, user_id: str, scan: int = 60) -> list[dict]:
    """Questions the student's LATEST attempt of got wrong and that can still be served, newest mistake first.
    A question drops out of the list by itself as soon as they answer it correctly in a later test."""
    qof = {}
    latest: dict[str, tuple[str, str]] = {}                        # question id -> (outcome, topic), later attempts overwrite earlier ones
    order: list[str] = []
    rows = conn.execute("SELECT a.id::text, ti.question_version_ids::text[] AS v FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id "
                        "WHERE a.user_id = %s::uuid AND a.status IN ('submitted', 'auto_submitted') ORDER BY a.started_at DESC LIMIT %s", (user_id, scan)).fetchall()
    for a in reversed(rows):
        for r in review(conn, a["id"], a["v"]):
            if r["id"] not in qof:
                qof[r["id"]] = conn.execute("SELECT question_id::text AS q FROM question_version WHERE id = %s::uuid", (r["id"],)).fetchone()["q"]
            q = qof[r["id"]]
            if r["outcome"] in ("correct", "wrong", "awarded_to_all"):
                latest[q] = r["outcome"]
                if q in order: order.remove(q)
                order.append(q)
    wrong = [q for q in reversed(order) if latest[q] == "wrong"]
    if not wrong:
        return []
    cur = {r["q"]: r for r in conn.execute(
        """SELECT s.question_id::text AS q, s.version_id::text AS version_id, s.marks, t.slug AS topic FROM v_servable_question s
           LEFT JOIN question_topic qt ON qt.question_id = s.question_id AND qt.is_primary LEFT JOIN topic t ON t.id = qt.topic_id
           WHERE s.question_id = ANY(%s::uuid[])""", (wrong,)).fetchall()}
    return [{"question_id": q, **{k: cur[q][k] for k in ("version_id", "marks", "topic")}} for q in wrong if q in cur]


def papers(conn) -> list[dict]:
    """Whole past papers a student can sit exactly as they were set: every one of the 65 questions is servable."""
    return conn.execute(
        """SELECT ps.year, ps.session_code AS sitting, count(*)::int AS questions, bool_and(s.rank_eligible) AS rank_eligible
           FROM v_servable_question s JOIN paper_session ps ON ps.id = s.session_id GROUP BY ps.year, ps.session_code
           HAVING count(*) = 65 ORDER BY ps.year DESC, ps.session_code""").fetchall()


def pyq_versions(conn, year: int, sitting: str) -> list[dict]:
    return conn.execute(
        """SELECT s.version_id::text AS version_id, s.rank_eligible, s.marks FROM v_servable_question s JOIN paper_session ps ON ps.id = s.session_id
           WHERE ps.year = %s AND ps.session_code = %s ORDER BY s.number""", (year, sitting)).fetchall()


def may_note(conn, user_id: str, version_id: str) -> str | None:
    """The question id, if this version is in one of the student's finished tests (only then can they bookmark or annotate it)."""
    r = conn.execute(
        """SELECT qv.question_id::text AS q FROM question_version qv WHERE qv.id = %s::uuid AND EXISTS
           (SELECT 1 FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id WHERE a.user_id = %s::uuid AND a.status <> 'in_progress' AND %s::uuid = ANY(ti.question_version_ids))""",
        (version_id, user_id, version_id)).fetchone()
    return r["q"] if r else None


def save_note(conn, user_id: str, question_id: str, bookmarked: bool | None, note: str | None) -> dict:
    return conn.execute(
        """INSERT INTO question_note (user_id, question_id, bookmarked, note) VALUES (%s::uuid, %s::uuid, COALESCE(%s, false), COALESCE(%s, ''))
           ON CONFLICT (user_id, question_id) DO UPDATE SET bookmarked = COALESCE(%s, question_note.bookmarked), note = COALESCE(%s, question_note.note), updated_at = now()
           RETURNING bookmarked, note""", (user_id, question_id, bookmarked, note, bookmarked, note)).fetchone()


def notes_for(conn, user_id: str, version_ids: list[str]) -> dict[str, dict]:
    """{version id: {bookmarked, note}} for the questions in a review."""
    rows = conn.execute(
        """SELECT qv.id::text AS v, n.bookmarked, n.note FROM question_note n JOIN question_version qv ON qv.question_id = n.question_id
           WHERE n.user_id = %s::uuid AND qv.id = ANY(%s::uuid[])""", (user_id, version_ids)).fetchall()
    return {r["v"]: {"bookmarked": r["bookmarked"], "note": r["note"]} for r in rows}


def bookmarks(conn, user_id: str) -> list[dict]:
    """Bookmarked questions that can still be served, newest bookmark first."""
    return conn.execute(
        """SELECT s.version_id::text AS version_id, s.marks, t.slug AS topic, ps.year, ps.session_code AS sitting, left(qv.stem_md, 140) AS stem, qv.extraction->>'display' AS display
           FROM question_note n JOIN v_servable_question s ON s.question_id = n.question_id JOIN question_version qv ON qv.id = s.version_id
           LEFT JOIN paper_session ps ON ps.id = s.session_id LEFT JOIN question_topic qt ON qt.question_id = s.question_id AND qt.is_primary LEFT JOIN topic t ON t.id = qt.topic_id
           WHERE n.user_id = %s::uuid AND n.bookmarked ORDER BY n.updated_at DESC""", (user_id,)).fetchall()
