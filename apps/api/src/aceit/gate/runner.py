"""Run the gate over the question bank. Only draft and held questions are touched: a live question is never re-held here
and a quarantined one is never restored (quarantine has no automatic undo, design §21.3).

    python -m aceit.gate --dry-run [--ocr]                     # measure: how many would pass checks 1 and 2 (needs no AI)
    python -m aceit.gate --solver gemini [--limit N]           # apply: needs GEMINI_API_KEY, makes 5 calls per question
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from aceit.gate import checks

SELECT_Q = """
SELECT q.id::text AS qid, qv.id::text AS vid, q.q_type, q.marks, q.status, COALESCE(ps.rank_eligible, false) AS session_rank,
       qv.stem_md AS stem, qv.options, qv.figures, qv.extraction,
       k.key_type, k.answer AS key, k.status AS key_status
FROM question q JOIN question_version qv ON qv.id = q.current_version_id
LEFT JOIN question_key k ON k.question_version_id = qv.id AND k.is_current
LEFT JOIN paper_session ps ON ps.id = q.session_id
"""
CANDIDATES = SELECT_Q + "WHERE q.origin = 'official_pyq' AND q.status = ANY(%s) ORDER BY ps.year, q.number"
ONE = SELECT_Q + "WHERE q.id = %s::uuid"


def crop_files(row: dict, root: Path) -> list[Path]:
    """The stored path starts with the folder name that ACEIT_CROPS_DIR already points at."""
    out = []
    for f in row["figures"] or []:
        p = Path(f["path"])
        out.append((root / p.relative_to(p.parts[0])).resolve())
    return [f for f in out if root.resolve() in f.parents and f.is_file()]


def solvable(row: dict, root: Path) -> tuple[dict, list[Path]]:
    """A database row as the gate's question dict, plus its page images."""
    imgs = crop_files(row, root)
    return {**row, "display": (row["extraction"] or {}).get("display", "text"), "crops_ok": len(imgs) >= 1 and len(imgs) == len(row["figures"] or [])}, imgs


def ocr(images: list[Path]) -> str:
    """The second reader: tesseract on the page crop (an engine independent of the PDF text layer)."""
    return " ".join(subprocess.run(["tesseract", str(i), "-", "--psm", "6"], capture_output=True, text=True, timeout=60).stdout for i in images)


class LlmSolver:
    """One independent solve per call, through whichever model is configured (aceit.llm). Sends the text, plus the page image when the text is unreliable."""

    def __init__(self, llm=None):
        from aceit import llm as _llm
        self.llm = llm or _llm.from_env() or (_ for _ in ()).throw(RuntimeError("set GEMINI_API_KEY"))
        self.MODEL = self.llm.MODEL

    def __call__(self, q: dict, images: list[Path]):
        shape = {"MCQ": '{"choice": "A"}', "MSQ": '{"choices": ["A", "C"]}', "NAT": '{"value": 2.5}'}[q["q_type"]]
        prompt = (f"Solve this GATE question yourself. Work carefully, then end with ONLY one JSON object of the form {shape}.\n\n"
                  + (checks.extracted_text(q) if q["display"] == "text" else "(the question is in the image)"))
        m = re.findall(r"\{[^{}]*\}", self.llm(prompt, images if q["display"] == "image" else [], max_tokens=8000, temperature=1.0))
        return json.loads(m[-1]) if m else None


def run(conn, root: Path, solver=None, use_ocr: bool = False, limit: int | None = None, apply: bool = False, statuses=("draft", "held")) -> dict:
    tally = {"seen": 0, "pass_checks_1_2": 0, "live": 0, "live_rank": 0, "held": 0, "reasons": {}}
    for row in conn.execute(CANDIDATES, (list(statuses),)).fetchall()[:limit]:
        q, imgs = solvable(row, root)
        bad = checks.structural(q) if row["key_type"] else ["no current key"]
        reader = checks.reader_agreement(checks.extracted_text(q), ocr(imgs)) if use_ocr and q["display"] == "text" and not bad and imgs else None
        solve = checks.solve_check(solver, q, imgs) if solver and not bad and row["key_type"] != "mta" else None
        d = checks.decide(bad, reader, solve, row["key_type"] or "")
        tally["seen"] += 1
        tally["pass_checks_1_2"] += not bad and (reader is None or reader >= checks.READER_MIN)
        tally["live" if d["status"] == "live" else "held"] += 1
        tally["live_rank"] += d["status"] == "live" and d["rank_ok"] and row["session_rank"]
        for r in d["reasons"]:
            tally["reasons"][re.sub(r"\d+%", "N%", r)] = tally["reasons"].get(re.sub(r"\d+%", "N%", r), 0) + 1
        if apply:
            if solve:
                conn.execute("INSERT INTO ai_check (question_version_id, model, solves, agree, answer, matches_key) VALUES (%s::uuid, %s, %s, %s, %s, %s)",
                             (row["vid"], getattr(solver, "MODEL", "custom"), solve["solves"], solve["agree"], Jsonb(solve["answer"]), solve["matches_key"]))
            gate = {"status": d["status"], "reasons": d["reasons"], "reader_agreement": reader, "solve": solve and solve["passed"]}
            conn.execute("UPDATE question_version SET extraction = extraction || %s WHERE id = %s::uuid", (Jsonb({"gate": gate}), row["vid"]))
            conn.execute("UPDATE question SET status = %s, rank_eligible = %s WHERE id = %s::uuid", (d["status"], d["status"] == "live" and d["rank_ok"] and row["session_rank"], row["qid"]))
    return tally


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--solver", choices=["gemini"], help="use Gemini (needs GEMINI_API_KEY)")
    ap.add_argument("--ocr", action="store_true", help="run the second reader (tesseract) on text-mode questions")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--all", action="store_true", help="dry run only: include live questions, to measure the whole bank")
    a = ap.parse_args()
    if not a.dry_run and not a.solver:
        ap.error("applying the gate needs --solver (without the AI solve nothing can pass check 3); use --dry-run to measure")
    if a.all and not a.dry_run:
        ap.error("--all is for measuring only")
    import psycopg
    root = Path(os.environ["ACEIT_CROPS_DIR"])
    with psycopg.connect(os.environ["ACEIT_DATABASE_URL"], row_factory=dict_row) as conn:
        t = run(conn, root, LlmSolver() if a.solver else None, a.ocr or bool(a.solver), a.limit, apply=not a.dry_run, statuses=("draft", "held", "live") if a.all else ("draft", "held"))
    print(json.dumps(t, indent=2))
    return 0
