"""The aceIt HTTP API (v1). Thin layer: validate, call the engine and the store, never hold exam logic itself."""
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from aceit.analytics.analysis import analyze
from aceit.analytics.progress import percentile, predicted_band
from aceit.platform import store
from aceit.quarantine import rules as quarantine
from aceit.platform.auth import JwksCache, caller
from aceit.platform.config import Settings, load
from aceit.session import attempt as engine
from aceit.testing.assembler import AssemblyError, build_full_mock, build_pair, build_topic_test

BLUEPRINT = Path(os.environ.get("ACEIT_BLUEPRINT", Path(__file__).resolve().parents[5] / "data" / "blueprints" / "gate_cs_v1.json"))


class NewTest(BaseModel):
    kind: Literal["full", "topic", "pyq", "retry"]
    source: Literal["mistakes", "bookmarks"] = "mistakes"                # retry: which of the student's own lists to practise
    year: int | None = None                                              # pyq: which past paper
    sitting: str | None = Field(None, max_length=8)
    topics: list[str] = Field(default_factory=list, max_length=20)      # syllabus slugs (use /v1/topics/resolve for free text)
    count: int = Field(20, ge=1, le=65)
    rank_only: bool = False                                              # True = only questions that may count towards rank
    seed: int | None = None


class UsernameIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_]{3,20}$")


class NewPair(BaseModel):
    rank_only: bool = False
    seed: int | None = None


class StartAttempt(BaseModel):
    test_id: UUID


class AutosaveItem(BaseModel):
    question_id: UUID
    response: dict | None = None
    palette_status: str = "not_answered"
    time_spent_s: int = Field(0, ge=0, le=20000)

    @field_validator("response")
    @classmethod
    def small(cls, v):
        if v is not None and len(json.dumps(v)) > 500:
            raise ValueError("response too large")
        return v


class NoteIn(BaseModel):
    bookmarked: bool | None = None
    note: str | None = Field(None, max_length=2000)


class Report(BaseModel):
    detail: str | None = Field(None, max_length=500)


class Autosave(BaseModel):
    seq: int = Field(ge=0)
    items: list[AutosaveItem] = Field(max_length=100)


def create_app(settings: Settings | None = None, pool: ConnectionPool | None = None, jwks: JwksCache | None = None, clock=None) -> FastAPI:
    app = FastAPI(title="aceIt API", version="0.1.0")
    app.state.settings = settings or load()
    st = app.state.settings
    if st.auth_mode == "jwt" and not (st.jwt_issuer and st.jwt_audience):         # never run production sign-in with the issuer or audience unchecked
        raise RuntimeError("jwt auth needs ACEIT_JWT_ISSUER and ACEIT_JWT_AUDIENCE (or ACEIT_COGNITO_REGION, ACEIT_COGNITO_POOL_ID and ACEIT_COGNITO_CLIENT_ID)")
    app.state.jwks = jwks or JwksCache(app.state.settings.jwks_url)
    app.state.pool = pool or ConnectionPool(app.state.settings.database_url, kwargs={"row_factory": dict_row}, min_size=1, max_size=10, open=True,
                                                       check=ConnectionPool.check_connection, max_idle=240)
    app.state.clock = clock or (lambda: datetime.now(timezone.utc))
    app.state.blueprint = json.loads(BLUEPRINT.read_text())

    def db(request: Request):
        with request.app.state.pool.connection() as conn:
            yield conn

    def user(request: Request, conn=Depends(db), who: dict = Depends(caller)) -> str:
        return store.upsert_user(conn, who["sub"], who.get("email"))

    @app.get("/v1/config")
    def config(request: Request):
        st = request.app.state.settings
        return {"auth_mode": st.auth_mode, "cognito": {"domain": st.cognito_domain, "client_id": st.cognito_client_id} if st.cognito_domain and st.cognito_client_id else None}

    @app.get("/v1/health")
    def health(conn=Depends(db)):
        conn.execute("SELECT 1")
        return {"ok": True}

    @app.get("/v1/me")
    def me(conn=Depends(db), uid: str = Depends(user)):
        return {"id": uid, "username": store.get_username(conn, uid)}

    @app.put("/v1/me/username")
    def choose_username(body: UsernameIn, conn=Depends(db), uid: str = Depends(user)):
        if not store.set_username(conn, uid, body.username):
            raise HTTPException(409, "That username is taken")
        return {"username": body.username}

    @app.get("/v1/me/export")
    def export_me(conn=Depends(db), uid: str = Depends(user)):
        return JSONResponse(jsonable_encoder(store.export_user(conn, uid)), headers={"Content-Disposition": 'attachment; filename="aceit-my-data.json"'})

    @app.delete("/v1/me", status_code=204)
    def delete_me(conn=Depends(db), uid: str = Depends(user)):
        store.delete_user(conn, uid)

    @app.get("/v1/topics/resolve")
    def resolve(q: str = Query(min_length=1, max_length=80), conn=Depends(db), uid: str = Depends(user)):
        return {"query": q, "matches": store.resolve_topic(conn, q)}

    @app.post("/v1/tests", status_code=201)
    def create_test(body: NewTest, request: Request, conn=Depends(db), uid: str = Depends(user)):
        seed = body.seed if body.seed is not None else secrets.randbelow(2**31)
        bp = request.app.state.blueprint
        seen = store.seen_versions(conn, uid)
        shelf_keys = (["full:rank"] if body.rank_only else ["full:rank", "full:practice"]) if body.kind == "full" and body.seed is None else \
                     [f"subject:{body.topics[0]}"] if body.kind == "topic" and len(body.topics) == 1 and body.count == 20 and body.seed is None and not body.rank_only else []
        shelved = store.pick_shelf(conn, shelf_keys, seen) if shelf_keys else None        # a ready-made test this student has not seen, if the nightly shelf has one
        if shelved:
            return {"id": shelved["id"], "kind": shelved["kind"], "questions": len(shelved["version_ids"]), "duration_s": shelved["duration_s"],
                    "rank_eligible": shelved["rank_eligible"], "seed": shelved["seed"]}
        try:
            if body.kind == "full":
                pool_ = store.load_pool(conn, request.app.state.settings.full_mock_min_year)
                plan = build_full_mock(pool_, bp, seed, seen=frozenset(seen), rank_only=body.rank_only)
                ids, duration, blueprint, rank = plan.question_ids, bp["duration_min"] * 60, bp["version"], not plan.relaxed and body.rank_only
            elif body.kind == "pyq":
                if body.year is None or not body.sitting:
                    raise HTTPException(422, "pick a past paper (year and sitting)")
                paper = store.pyq_versions(conn, body.year, body.sitting)
                if len(paper) != 65:
                    raise HTTPException(422, "that paper is not fully available yet")
                ids, duration, blueprint, rank = [p["version_id"] for p in paper], bp["duration_min"] * 60, None, all(p["rank_eligible"] for p in paper)
            elif body.kind == "retry":
                mine = (store.mistakes(conn, uid) if body.source == "mistakes" else store.bookmarks(conn, uid))[:body.count]
                if not mine:
                    raise HTTPException(422, "you have no mistakes to retry yet" if body.source == "mistakes" else "you have no bookmarked questions yet")
                ids, duration, blueprint, rank = [m["version_id"] for m in mine], max(600, sum(m["marks"] for m in mine) * 108), None, False
            else:
                if not body.topics:
                    raise HTTPException(422, "topic tests need at least one topic")
                pool_ = store.load_pool(conn)
                ids = build_topic_test(pool_, set(body.topics), body.count, seed, seen=frozenset(seen), rank_only=body.rank_only)
                marks = sum(c.marks for c in pool_ if c.id in set(ids))
                duration, blueprint, rank = max(600, marks * 108), None, False
        except AssemblyError as e:
            raise HTTPException(422, str(e))
        tid = store.create_test(conn, uid, "custom" if body.kind == "retry" else body.kind, seed, ids, duration, rank, blueprint)
        return {"id": tid, "kind": body.kind, "questions": len(ids), "duration_s": duration, "rank_eligible": rank, "seed": seed}

    @app.post("/v1/test-pairs", status_code=201)
    def create_pair(body: NewPair, request: Request, conn=Depends(db), uid: str = Depends(user)):
        """Two full mocks from the same blueprint with no question in common (a CS1/CS2-style pair). Served from the shelf when possible."""
        seen = store.seen_versions(conn, uid)
        sets = store.pick_shelf_pair(conn, ["pair:rank"] if body.rank_only else ["pair:rank", "pair:practice"], seen) if body.seed is None else None
        if not sets:
            seed, bp = body.seed if body.seed is not None else secrets.randbelow(2**31), request.app.state.blueprint
            try:
                one, two = build_pair(store.load_pool(conn, request.app.state.settings.full_mock_min_year), bp, seed, seen=frozenset(seen), rank_only=body.rank_only)
            except AssemblyError as e:
                raise HTTPException(422, str(e))
            pid, rank = str(uuid4()), body.rank_only and not (one.relaxed or two.relaxed)
            for n, plan in ((1, one), (2, two)):
                store.create_test(conn, uid, "full", plan.seed, plan.question_ids, bp["duration_min"] * 60, rank, bp["version"], pair_id=pid, pair_set=n)
            sets = store.pair_sets(conn, pid)
        return {"pair_id": sets[0]["pair_id"], "sets": [{k: v for k, v in s_.items() if k != "pair_id"} for s_ in sets]}

    @app.get("/v1/test-pairs/{pair_id}")
    def pair_progress(pair_id: UUID, conn=Depends(db), uid: str = Depends(user)):
        sets = store.pair_status(conn, str(pair_id), uid)
        if not sets:
            raise HTTPException(404, "pair not found")
        return {"pair_id": str(pair_id), "sets": sets}

    @app.get("/v1/tests/{test_id}")
    def get_test(test_id: UUID, conn=Depends(db), uid: str = Depends(user)):
        t = store.get_test(conn, str(test_id), uid)
        if not t:
            raise HTTPException(404, "test not found")
        return {"id": t["id"], "kind": t["kind"], "questions": len(t["version_ids"]), "duration_s": t["duration_s"], "rank_eligible": t["rank_eligible"]}

    def attempt_view(conn, row: dict, a: engine.Attempt, now: datetime) -> dict:
        return {"id": row["id"], "kind": row["kind"], "last_seq": row["last_seq"], "status": a.status, "server_now": now.isoformat(), "started_at": a.started_at.isoformat(),
                "deadline_at": a.deadline_at.isoformat(), "remaining_s": engine.remaining_s(a, now),
                "questions": store.question_payload(conn, row["version_ids"]),
                "responses": {q: {"response": r.response, "palette_status": r.palette_status, "time_spent_s": r.time_spent_s} for q, r in a.responses.items()}}

    @app.post("/v1/attempts", status_code=201)
    def start(body: StartAttempt, request: Request, conn=Depends(db), uid: str = Depends(user)):
        t = store.get_test(conn, str(body.test_id), uid)
        if not t:
            raise HTTPException(404, "test not found")
        now = request.app.state.clock()
        existing = conn.execute("SELECT id::text FROM attempt WHERE test_instance_id = %s::uuid AND user_id = %s::uuid AND status = 'in_progress'", (t["id"], uid)).fetchone()
        if existing:                                                     # starting twice resumes, it never restarts the clock
            row = store.lock_attempt(conn, existing["id"], uid)
        else:
            a0 = engine.start_attempt("new", uid, now, t["duration_s"])
            row = store.lock_attempt(conn, store.create_attempt(conn, t["id"], uid, a0.started_at, a0.deadline_at), uid)
        return attempt_view(conn, row, store.engine_attempt(conn, row), now)

    @app.get("/v1/attempts")
    def attempts(conn=Depends(db), uid: str = Depends(user)):
        return store.list_attempts(conn, uid)

    @app.get("/v1/attempts/{attempt_id}")
    def resume(attempt_id: UUID, request: Request, conn=Depends(db), uid: str = Depends(user)):
        row = store.lock_attempt(conn, str(attempt_id), uid)
        if not row:
            raise HTTPException(404, "attempt not found")
        return attempt_view(conn, row, store.engine_attempt(conn, row), request.app.state.clock())

    @app.put("/v1/attempts/{attempt_id}/responses")
    def autosave(attempt_id: UUID, body: Autosave, request: Request, conn=Depends(db), uid: str = Depends(user)):
        row = store.lock_attempt(conn, str(attempt_id), uid)
        if not row:
            raise HTTPException(404, "attempt not found")
        now = request.app.state.clock()
        a = store.engine_attempt(conn, row)
        result = engine.apply_autosave(a, [i.model_dump(mode="json") for i in body.items], body.seq, now, allowed_questions=set(row["version_ids"]))
        if result["accepted"] and result["reason"] == "ok":
            store.save_responses(conn, str(attempt_id), a, {str(i.question_id) for i in body.items}, now)
        if not result["accepted"]:
            raise HTTPException(409 if result["reason"] in ("attempt_closed", "too_late") else 422, result["reason"])
        return result

    @app.post("/v1/attempts/{attempt_id}/submit")
    def submit(attempt_id: UUID, request: Request, conn=Depends(db), uid: str = Depends(user)):
        row = store.lock_attempt(conn, str(attempt_id), uid)
        if not row:
            raise HTTPException(404, "attempt not found")
        return store.finish_attempt(conn, row, request.app.state.clock())

    @app.get("/v1/attempts/{attempt_id}/result")
    def result(attempt_id: UUID, conn=Depends(db), uid: str = Depends(user)):
        row = store.lock_attempt(conn, str(attempt_id), uid)
        if not row:
            raise HTTPException(404, "attempt not found")
        if row["status"] == "in_progress":
            raise HTTPException(409, "attempt still in progress")
        return row["result"]

    @app.get("/v1/attempts/{attempt_id}/review")
    def review(attempt_id: UUID, conn=Depends(db), uid: str = Depends(user)):
        row = store.lock_attempt(conn, str(attempt_id), uid)
        if not row:
            raise HTTPException(404, "attempt not found")
        if row["status"] == "in_progress":
            raise HTTPException(409, "attempt still in progress")          # the key is revealed only after the test is over
        rows = store.review(conn, row["id"], row["version_ids"])
        notes = store.notes_for(conn, uid, row["version_ids"])
        return [{**r, "bookmarked": notes.get(r["id"], {}).get("bookmarked", False), "note": notes.get(r["id"], {}).get("note", "")} for r in rows]

    @app.get("/v1/attempts/{attempt_id}/analysis")
    def analysis(attempt_id: UUID, request: Request, conn=Depends(db), uid: str = Depends(user)):
        row = store.lock_attempt(conn, str(attempt_id), uid)
        if not row:
            raise HTTPException(404, "attempt not found")
        if row["status"] == "in_progress":
            raise HTTPException(409, "attempt still in progress")
        out = analyze(store.review(conn, row["id"], row["version_ids"]))
        ranked = bool(row["result"] and row["result"].get("rank_eligible")) and row["blueprint_version"]
        prev = store.previous_attempt(conn, uid, row["id"], row["kind"])
        if prev and prev["max_score"] and row["result"]:
            now_pct, was_pct = 100 * row["result"]["score"] / row["result"]["max_score"], 100 * prev["score"] / prev["max_score"]
            out["vs_previous"] = {"previous_attempt_id": prev["id"], "percent_now": round(now_pct, 1), "percent_before": round(was_pct, 1), "change": round(now_pct - was_pct, 1),
                                  "wrong_before": prev["wrong"], "wrong_now": row["result"]["counts"].get("wrong", 0), "skipped_before": prev["unattempted"], "skipped_now": row["result"]["counts"].get("unattempted", 0)}
        else:
            out["vs_previous"] = None
        out["cohort"] = percentile(row["result"]["score"], store.cohort_scores(conn, uid, row["blueprint_version"])) if ranked else None
        return out

    @app.put("/v1/questions/{version_id}/note")
    def note_question(version_id: UUID, body: NoteIn, conn=Depends(db), uid: str = Depends(user)):
        q = store.may_note(conn, uid, str(version_id))
        if not q:
            raise HTTPException(404, "no such question in your finished tests")
        return store.save_note(conn, uid, q, body.bookmarked, body.note)

    @app.get("/v1/me/bookmarks")
    def my_bookmarks(conn=Depends(db), uid: str = Depends(user)):
        b = store.bookmarks(conn, uid)
        return {"count": len(b), "items": b}

    @app.get("/v1/papers")
    def past_papers(conn=Depends(db), uid: str = Depends(user)):
        return store.papers(conn)

    @app.get("/v1/me/mistakes")
    def my_mistakes(conn=Depends(db), uid: str = Depends(user)):
        m = store.mistakes(conn, uid)
        by = {}
        for x in m:
            by[x["topic"] or "unknown"] = by.get(x["topic"] or "unknown", 0) + 1
        return {"count": len(m), "topics": [{"topic": t, "count": n} for t, n in sorted(by.items(), key=lambda kv: -kv[1])]}

    @app.get("/v1/me/progress")
    def progress(request: Request, conn=Depends(db), uid: str = Depends(user)):
        stats = store.subject_stats(conn, uid)
        return {"subjects": stats, "predicted": predicted_band(stats, request.app.state.blueprint)}

    @app.post("/v1/questions/{version_id}/report", status_code=201)
    def report_question(version_id: UUID, body: Report, request: Request, conn=Depends(db), uid: str = Depends(user)):
        row = conn.execute(                                              # only a student who was given the question may report it
            """SELECT qv.question_id::text AS q FROM question_version qv WHERE qv.id = %s::uuid AND EXISTS
               (SELECT 1 FROM attempt a JOIN test_instance ti ON ti.id = a.test_instance_id WHERE a.user_id = %s::uuid AND a.status <> 'in_progress' AND %s::uuid = ANY(ti.question_version_ids))""",
            (str(version_id), uid, str(version_id))).fetchone()
        if not row:
            raise HTTPException(404, "no such question in your finished tests")
        return {"recorded": quarantine.report(conn, row["q"], uid, body.detail, request.app.state.clock())}

    @app.get("/v1/questions/{version_id}/images/{n}")
    def question_image(version_id: UUID, n: int, request: Request, conn=Depends(db), uid: str = Depends(user)):
        root = os.environ.get("ACEIT_CROPS_DIR")
        rel = store.figure_path(conn, uid, str(version_id), n) if root and 0 <= n < 20 else None
        if not rel:
            raise HTTPException(404, "no such image")
        base = Path(root).resolve()
        f = (base / Path(rel).relative_to(Path(rel).parts[0])).resolve()   # the stored path starts with the folder name
        if base not in f.parents or not f.is_file():                        # never leave the crops folder
            raise HTTPException(404, "no such image")
        return FileResponse(f, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    class NoCacheStatic(StaticFiles):                                    # always revalidate, so a deploy shows up at once
        async def get_response(self, path, scope):
            r = await super().get_response(path, scope)
            r.headers["Cache-Control"] = "no-cache"
            return r

    web = Path(os.environ.get("ACEIT_WEB_DIR", Path(__file__).resolve().parents[4] / "web"))
    if web.is_dir():                                                     # the web app is served by the same process in development
        app.mount("/", NoCacheStatic(directory=web, html=True), name="web")
    return app
