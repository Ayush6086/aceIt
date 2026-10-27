"""The automatic publish gate (design §21.3). Three independent checks, then one decision. Pure code: no database, no network.

A question q is a dict: q_type, marks, display ('text' | 'image'), stem, options (list | None), crops_ok (bool),
key_type, key (dict | None), key_status, and for the decision the results of the other two checks.
"""
import json
import re
from collections import Counter

from aceit.scoring.marks import score_question

READER_MIN = 0.90          # share of the extracted words, digits and option letters the second reader also sees
SOLVE_RUNS = 5
SOLVE_MIN_AGREE = 4        # of 5 solves must give the same answer, and that answer must be the official key
LABELS = ["A", "B", "C", "D"]


# ---- check 2: schema and rendering validators ---------------------------------------------------------------
def structural(q: dict) -> list[str]:
    """Reasons the question is malformed (empty list = fine)."""
    bad, t, opts = [], q["q_type"], q.get("options")
    if q["marks"] not in (1, 2):
        bad.append(f"marks {q['marks']}")
    if not q.get("crops_ok"):
        bad.append("original page image missing")
    if q["display"] == "text" and not (q.get("stem") or "").strip():
        bad.append("empty question text")
    if t == "NAT":
        if opts:
            bad.append("numerical question has options")
    elif q["display"] == "text":
        if [o.get("label") for o in opts or []] != LABELS or not all((o.get("text") or "").strip() for o in opts):
            bad.append("options are not four labelled A-D with text")
    elif opts and [o.get("label") for o in opts] != LABELS:
        bad.append("option labels are not A-D")
    ks, key = q["key_status"], q.get("key")
    if ks not in ("OFFICIAL", "OFFICIAL_MTA"):
        bad.append(f"key status {ks}")
    elif q["key_type"] != "mta":
        if q["key_type"] != t.lower():
            bad.append(f"key type {q['key_type']} does not fit a {t} question")
        else:
            for k in (key or {}).get("any_of", [key]):
                if t == "MCQ" and k.get("choice") not in LABELS:
                    bad.append("key letter outside A-D")
                elif t == "MSQ" and not (k.get("choices") and set(k["choices"]) <= set(LABELS)):
                    bad.append("key letters outside A-D")
                elif t == "NAT":
                    try:
                        if float(k["min"]) > float(k["max"]):
                            bad.append("key range is reversed")
                    except (KeyError, TypeError, ValueError):
                        bad.append("key range is not numeric")
    return bad


# ---- check 1: a second, independent reader of the same page ------------------------------------------------
def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def reader_agreement(extracted: str, second: str) -> float:
    """Share of the text-layer tokens (counted with repeats) that the second reader also produced."""
    a, b = Counter(tokens(extracted)), Counter(tokens(second))
    total = sum(a.values())
    return 1.0 if total == 0 else sum(min(n, b[t]) for t, n in a.items()) / total


def extracted_text(q: dict) -> str:
    return (q.get("stem") or "") + " " + " ".join(f"{o['label']} {o.get('text') or ''}" for o in q.get("options") or [])


# ---- check 3: independent solves against the official key --------------------------------------------------
def solve_check(solver, q: dict, images: list, runs: int = SOLVE_RUNS) -> dict:
    """solver(q, images) -> a response dict ({"choice"}, {"choices"} or {"value"}) or None. Returns the evidence stored in ai_check."""
    answers = []
    for _ in range(runs):
        try:
            r = solver(q, images)
        except Exception:                      # a failed call is a missing solve, never an agreement
            r = None
        answers.append(r)
    canon = [json.dumps(r, sort_keys=True) for r in answers if r]
    top, agree = (Counter(canon).most_common(1)[0] if canon else (None, 0))
    answer = json.loads(top) if top else None
    matches = bool(answer) and score_question(q["q_type"], q["marks"], q["key_type"], q["key"], answer).status == "correct"
    return {"solves": runs, "agree": agree, "answer": answer, "matches_key": matches, "passed": agree >= SOLVE_MIN_AGREE and matches}


# ---- the decision -------------------------------------------------------------------------------------------
def decide(structural_problems: list[str], reader: float | None, solve: dict | None, key_type: str) -> dict:
    """-> {"status": 'live' | 'held', "rank_ok": bool, "reasons": [...]}.
    reader None = not needed (the student is shown the original image, so extracted text cannot mislead them).
    solve None = the AI solve has not run: never a pass. Marks-to-all keys need no solve (the key says everyone gets the marks)."""
    why = list(structural_problems)
    solved = key_type == "mta" or bool(solve and solve["passed"])
    if not solved:
        why.append("ai solve not run" if solve is None else "ai solve does not support the official key")
    reader_ok = reader is None or reader >= READER_MIN
    if reader is not None and not reader_ok:
        why.append(f"second reader agrees on only {reader:.0%} of the text")
    if structural_problems or not solved:
        return {"status": "held", "rank_ok": False, "reasons": why}
    # structure and solve pass: usable. A text the second reader doubts is practice-only (design: "unverified text" flag).
    return {"status": "live", "rank_ok": reader_ok, "reasons": why}
