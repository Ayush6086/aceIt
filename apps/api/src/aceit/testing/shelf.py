"""The nightly test shelf (design §21.1): ready-made shared tests, so a student gets a test at once and everyone on the same
shelf test is ranked on the same questions. Built by the same seeded assembler and validator as on-demand tests.

Shelf keys: pair:rank and pair:practice (two linked full mocks with no question in common, like CS1 and CS2), full:rank (only ranking-eligible questions, never relaxed), full:practice (any servable questions, may be relaxed
and is never ranked), subject:<slug> (20 questions of one subject). Each night: retire shelf tests that hold a question that is
no longer servable (quarantined, held) or are older than MAX_AGE_DAYS, then top every key back up to its target.
Tests already attempted are never deleted, only taken off the shelf.
"""
import os
import secrets

from aceit.platform import store
from uuid import uuid4

from aceit.testing.assembler import AssemblyError, build_full_mock, build_pair, build_topic_test

TARGETS = {"full:rank": 4, "full:practice": 4}
PAIR_TARGETS = {"pair:rank": 2, "pair:practice": 2}         # pairs, i.e. two tests each
SUBJECT_TARGET, SUBJECT_QUESTIONS = 2, 20
MAX_AGE_DAYS = 14


def restock(conn, bp: dict, min_year: int | None = None, rng=secrets.randbelow) -> dict:
    min_year = min_year if min_year is not None else int(os.environ.get("ACEIT_FULL_MOCK_MIN_YEAR", "2018"))
    out = {"retired": 0, "added": {}, "cannot_build": []}
    out["retired"] = conn.execute(                                       # a pair leaves the shelf as a whole: if either set is bad, both go
        """WITH bad AS (SELECT ti.id, ti.pair_id FROM test_instance ti WHERE shelf_key IS NOT NULL AND (
               created_at < now() - make_interval(days => %s)
               OR EXISTS (SELECT 1 FROM unnest(ti.question_version_ids) AS v(id) WHERE NOT EXISTS (SELECT 1 FROM v_servable_question s WHERE s.version_id = v.id))))
           UPDATE test_instance SET shelf_key = NULL WHERE shelf_key IS NOT NULL
             AND (id IN (SELECT id FROM bad) OR pair_id IN (SELECT pair_id FROM bad WHERE pair_id IS NOT NULL))""",
        (MAX_AGE_DAYS,)).rowcount
    have = {r["shelf_key"]: r["n"] for r in conn.execute("SELECT shelf_key, count(*) AS n FROM test_instance WHERE shelf_key IS NOT NULL GROUP BY 1").fetchall()}
    full_pool, all_pool = store.load_pool(conn, min_year), store.load_pool(conn)
    for key, target in {**TARGETS, **{f"subject:{s}": SUBJECT_TARGET for s in sorted(bp["subject_marks"])}}.items():
        for _ in range(max(0, target - have.get(key, 0))):
            seed = rng(2**31)
            try:
                if key.startswith("full:"):
                    plan = build_full_mock(full_pool, bp, seed, rank_only=key == "full:rank")
                    ids, dur, kind, rank = plan.question_ids, bp["duration_min"] * 60, "full", key == "full:rank" and not plan.relaxed
                    if key == "full:rank" and plan.relaxed:
                        raise AssemblyError("only a relaxed test was possible")
                else:
                    ids = build_topic_test(all_pool, {key.split(":", 1)[1]}, SUBJECT_QUESTIONS, seed)
                    marks = sum(c.marks for c in all_pool if c.id in set(ids))
                    dur, kind, rank = max(600, marks * 108), "subject", False
            except AssemblyError as e:
                out["cannot_build"].append(f"{key}: {e}")
                break                                            # the pool will not change within this run: do not retry this key
            store.create_test(conn, None, kind, seed, ids, dur, rank, bp["version"] if kind == "full" else None, shelf_key=key)
            out["added"][key] = out["added"].get(key, 0) + 1
    for key, target in PAIR_TARGETS.items():
        for _ in range(max(0, target - have.get(key, 0) // 2)):
            seed = rng(2**31)
            try:
                one, two = build_pair(full_pool, bp, seed, rank_only=key == "pair:rank")
                if key == "pair:rank" and (one.relaxed or two.relaxed):
                    raise AssemblyError("only a relaxed test was possible")
            except AssemblyError as e:
                out["cannot_build"].append(f"{key}: {e}")
                break
            pid, rank = str(uuid4()), key == "pair:rank"
            for n, plan in ((1, one), (2, two)):
                store.create_test(conn, None, "full", plan.seed, plan.question_ids, bp["duration_min"] * 60, rank, bp["version"], shelf_key=key, pair_id=pid, pair_set=n)
            out["added"][key] = out["added"].get(key, 0) + 2
    return out
