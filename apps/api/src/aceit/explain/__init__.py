"""Written explanations for questions (design §7, `question_version.solution_md`).

An explanation is AI-written and is only stored when it ends in an answer that the OFFICIAL key accepts: a model that cannot reach the
official answer is more likely to have misread the question than to have found a key error, so its text is thrown away, never shown.
Students see an explanation only after the test is over, labelled as AI-written.

    python -m aceit.explain --limit 50        # needs GEMINI_API_KEY; writes explanations for live questions that have none
"""
import argparse
import json
import os
import re
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from aceit.gate import checks, runner
from aceit.scoring.marks import score_question

MIN_CHARS, MAX_CHARS = 40, 2500


def key_text(key_type: str, key: dict | None) -> str:
    """The official answer in words, e.g. 'B', 'A, C', '2.5 to 3'."""
    if key_type in ("mta", "dropped") or not key:
        return ""
    if "any_of" in key:
        return " or ".join(key_text(key_type, k) for k in key["any_of"])
    if key_type == "mcq":
        return key["choice"]
    if key_type == "msq":
        return ", ".join(sorted(key["choices"]))
    return str(key["min"]) if str(key["min"]) == str(key["max"]) else f"{key['min']} to {key['max']}"


def parse(text: str) -> tuple[str, dict | None]:
    """Split 'explanation ... FINAL ANSWER: {json}' into the explanation and the answer the writer reached."""
    m = list(re.finditer(r"FINAL ANSWER:\s*(\{[^{}]*\})", text or ""))
    if not m:
        return (text or "").strip(), None
    try:
        return text[:m[-1].start()].strip(), json.loads(m[-1].group(1))
    except ValueError:
        return text[:m[-1].start()].strip(), None


def accept(q: dict, text: str) -> tuple[str | None, str]:
    """-> (explanation to store | None, reason). Stored only if it is a sensible length and its own final answer scores as correct against the official key."""
    body, answer = parse(text)
    if answer is None:
        return None, "no final answer"
    if not (MIN_CHARS <= len(body) <= MAX_CHARS):
        return None, "explanation too short or too long"
    if score_question(q["q_type"], q["marks"], q["key_type"], q["key"], answer).status != "correct":
        return None, "its answer is not the official answer"
    return body, "ok"


class LlmExplainer:
    def __init__(self, llm=None):
        from aceit import llm as _llm
        self.llm = llm or _llm.from_env() or (_ for _ in ()).throw(RuntimeError("set GEMINI_API_KEY"))
        self.MODEL = self.llm.MODEL

    def __call__(self, q: dict, images: list[Path], official: str) -> str:
        shape = {"MCQ": '{"choice": "B"}', "MSQ": '{"choices": ["A", "C"]}', "NAT": '{"value": 2.5}'}[q["q_type"]]
        prompt = (f"This is a GATE Computer Science question. The official answer is {official}. Explain, for a student who got it wrong, how to reach that answer: "
                  "state the key idea, then the steps, in plain language, in under 180 words, without repeating the question. Do not argue with the official answer. "
                  f"Write any mathematics as LaTeX between single dollar signs, for example $2^{{10}} = 1024$ or $\\frac{{a}}{{b}}$, and never use a dollar sign for money. "
                  f"End with one last line exactly of the form FINAL ANSWER: {shape} giving the answer your explanation reaches.\n\n"
                  + (checks.extracted_text(q) if q["display"] == "text" else "(the question is in the image)"))
        return self.llm(prompt, images if q["display"] == "image" else [], max_tokens=6000, temperature=0.4)


TODO = runner.SELECT_Q + """WHERE q.origin = 'official_pyq' AND q.status = 'live' AND qv.solution_md IS NULL AND k.key_type IN ('mcq', 'msq', 'nat')
                            AND k.status IN ('OFFICIAL') ORDER BY ps.year DESC, q.number"""


def run(conn, root: Path, explainer, limit: int | None = None) -> dict:
    """Write explanations for live questions that have none. Returns counts; every rejection is counted by reason."""
    out = {"seen": 0, "stored": 0, "rejected": {}}
    for row in conn.execute(TODO).fetchall()[:limit]:
        q, imgs = runner.solvable(row, root)
        out["seen"] += 1
        try:
            body, why = accept(q, explainer(q, imgs, key_text(row["key_type"], row["key"])))
        except Exception as e:                                   # a failed call is a missing explanation, never a half-stored one
            body, why = None, f"call failed: {type(e).__name__}"
        if body is None:
            out["rejected"][why] = out["rejected"].get(why, 0) + 1
            continue
        conn.execute("UPDATE question_version SET solution_md = %s, solution_src = 'ai', extraction = extraction || %s WHERE id = %s::uuid",
                     (body, Jsonb({"explanation": {"model": getattr(explainer, "MODEL", "custom"), "checked_against_official_key": True}}), row["vid"]))
        out["stored"] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=50)
    a = ap.parse_args()
    import psycopg
    with psycopg.connect(os.environ["ACEIT_DATABASE_URL"], row_factory=dict_row, autocommit=True) as conn:
        print(json.dumps(run(conn, Path(os.environ["ACEIT_CROPS_DIR"]), LlmExplainer(), a.limit), indent=2))
    return 0
