"""Per-attempt analysis (design §9). Pure code over the review rows of one attempt. No AI: every insight is a rule over
the student's own numbers, so it can be explained and tested.

A row is: {position, section, type, marks, topic, outcome, marks_awarded, time_spent_s}
outcome is one of correct | wrong | unattempted | awarded_to_all | not_scored.
"""
from collections import defaultdict

SECONDS_PER_MARK = 108          # 180 minutes for 100 marks: the real exam's pace
SCORED = ("correct", "wrong", "unattempted", "awarded_to_all")


def subject_of(topic: str | None) -> str:
    return (topic or "unknown").split("/")[0]


def analyze(rows: list[dict]) -> dict:
    rows = [r for r in rows if r["outcome"] in SCORED]
    expected = lambda r: r["marks"] * SECONDS_PER_MARK

    # ---- marks: where they came from and where they went
    earned = sum(r["marks_awarded"] for r in rows if r["marks_awarded"] > 0)
    negative = -sum(r["marks_awarded"] for r in rows if r["marks_awarded"] < 0)
    wrong = [r for r in rows if r["outcome"] == "wrong"]
    skipped = [r for r in rows if r["outcome"] == "unattempted"]
    marks = {"earned": round(earned, 2), "lost_to_negative_marking": round(negative, 2),
             "left_unattempted": sum(r["marks"] for r in skipped), "unattempted_questions": len(skipped),
             "possible": sum(r["marks"] for r in rows)}

    # ---- topics and subjects
    def group(key):
        g = defaultdict(lambda: {"correct": 0, "wrong": 0, "unattempted": 0, "possible": 0, "earned": 0.0, "time_s": 0, "expected_s": 0})
        for r in rows:
            k = key(r)
            if not k:
                continue
            x = g[k]
            x["possible"] += r["marks"]; x["earned"] += r["marks_awarded"]; x["time_s"] += r["time_spent_s"]; x["expected_s"] += expected(r)
            x["correct" if r["outcome"] in ("correct", "awarded_to_all") else r["outcome"]] += 1
        out = []
        for k, x in g.items():
            attempted = x["correct"] + x["wrong"]
            out.append({"key": k, **x, "earned": round(x["earned"], 2), "marks_lost": round(x["possible"] - x["earned"], 2),
                        "accuracy": round(x["correct"] / attempted, 2) if attempted else None})
        return sorted(out, key=lambda t: (-t["marks_lost"], t["key"]))
    topics, subjects = group(lambda r: r["topic"]), group(lambda r: subject_of(r["topic"]))

    # ---- time
    slow = sorted((r for r in rows if r["time_spent_s"] > max(240, 2.5 * expected(r))), key=lambda r: -r["time_spent_s"])[:5]
    rushed = [r for r in wrong if 0 < r["time_spent_s"] < 0.25 * expected(r)]
    by_section = {}
    for sec in sorted({r["section"] for r in rows}):
        part = [r for r in rows if r["section"] == sec]
        by_section[sec] = {"questions": len(part), "attempted": sum(1 for r in part if r["outcome"] != "unattempted"),
                           "used_s": sum(r["time_spent_s"] for r in part), "expected_s": sum(expected(r) for r in part)}
    time = {"used_s": sum(r["time_spent_s"] for r in rows), "expected_s": sum(expected(r) for r in rows), "by_section": by_section,
            "slow": [_q(r, expected(r)) for r in slow], "rushed_wrong": [_q(r, expected(r)) for r in rushed]}

    # ---- insights: plain rules over the numbers above
    insights = []
    if marks["left_unattempted"] >= 3:
        worst = max(subjects, key=lambda s: s["unattempted"], default=None)
        where = f", most of them in {worst['key']}" if worst and worst["unattempted"] >= 2 else ""
        insights.append({"kind": "skipped", "text": f"You left {marks['left_unattempted']} marks on the table: {marks['unattempted_questions']} questions were not attempted{where}."})
    mcq_wrong = sum(1 for r in wrong if r["type"] == "MCQ")
    if marks["lost_to_negative_marking"] >= 1:
        insights.append({"kind": "negative", "text": f"Negative marking cost you {marks['lost_to_negative_marking']} marks across {mcq_wrong} wrong multiple-choice answers. When you cannot rule out at least two options, skipping is usually the better bet."})
    sink = max((s for s in subjects if s["time_s"] >= 600), key=lambda s: s["time_s"] / max(1, s["expected_s"]), default=None)
    if sink and sink["time_s"] > 1.5 * sink["expected_s"]:
        insights.append({"kind": "time", "text": f"Most of your extra time went into {sink['key']}: {round(sink['time_s'] / 60)} min against about {round(sink['expected_s'] / 60)} min for its {sink['possible']} marks."})
    weak = next((t for t in topics if t["marks_lost"] > 0 and t["wrong"] + t["unattempted"] > 0), None)
    if weak:
        insights.append({"kind": "weak", "text": f"Weakest topic: {weak['key']}. You lost {weak['marks_lost']} of {weak['possible']} marks there ({weak['wrong']} wrong, {weak['unattempted']} not attempted)."})
    if len(rushed) >= 2:
        insights.append({"kind": "rushed", "text": f"{len(rushed)} wrong answers came in under a quarter of the expected time. Slow down on questions like these and re-read the options."})
    strong = next((t for t in sorted(topics, key=lambda t: -t["correct"]) if t["correct"] >= 2 and t["wrong"] == 0 and t["unattempted"] == 0), None)
    if strong:
        insights.append({"kind": "strong", "text": f"Solid: {strong['key']}. You got all {strong['correct']} questions right."})

    # ---- what to practise next: the topics that cost the most marks
    nxt = [{"topic": t["key"], "marks_lost": t["marks_lost"], "wrong": t["wrong"], "unattempted": t["unattempted"]}
           for t in topics if t["marks_lost"] > 0 and t["wrong"] + t["unattempted"] > 0][:3]
    reasons = classify(rows)
    return {"marks": marks, "time": time, "topics": topics, "subjects": subjects, "insights": insights[:6], "next_practice": nxt,
            "why": why_summary(rows, reasons), "per_question": [{"position": p, "reason": k} for p, k in sorted(reasons.items())]}


REASONS = {   # key -> (short label, what to do about it)
    "silly": ("Answered too fast", "Re-read the question and every option before you commit; these were wrong in under a quarter of the expected time."),
    "careless": ("Careless slip", "You get this topic right elsewhere in this test; check units, signs and the exact wording."),
    "slow": ("Took very long, still wrong", "Likely a concept gap: revise the idea, then retry the question."),
    "concept": ("Concept gap", "Revise this topic, then retry the question from your mistakes list."),
    "skipped": ("Skipped", "Attempt the questions you can do first, then come back; skipping costs nothing but unattempted marks are lost for good."),
    "not_reached": ("Ran out of time", "Practise pace: aim for about 108 seconds per mark and move on when stuck."),
}


def classify(rows: list[dict]) -> dict[int, str]:
    """Why each question lost marks: {position: reason key}. Plain rules over this attempt only; a guess, not a diagnosis."""
    topic_acc = {}
    for r in rows:
        if r["outcome"] in ("correct", "wrong") and r["topic"]:
            a = topic_acc.setdefault(r["topic"], [0, 0]); a[1] += 1; a[0] += r["outcome"] == "correct"
    ordered = sorted(rows, key=lambda r: r["position"])
    untouched_after, seen_touched = {}, False
    for r in reversed(ordered):                         # a question is "not reached" when it and everything after it was never touched
        touched = r["outcome"] != "unattempted" or r["time_spent_s"] > 0
        seen_touched = seen_touched or touched
        untouched_after[r["position"]] = not seen_touched
    out = {}
    for r in rows:
        exp = r["marks"] * SECONDS_PER_MARK
        if r["outcome"] == "unattempted":
            out[r["position"]] = "not_reached" if untouched_after[r["position"]] else "skipped"
        elif r["outcome"] == "wrong":
            c, n = topic_acc.get(r["topic"], [0, 0])
            if 0 < r["time_spent_s"] < 0.25 * exp: out[r["position"]] = "silly"
            elif r["time_spent_s"] > 2 * exp: out[r["position"]] = "slow"
            elif n - 1 >= 3 and c / (n - 1) >= 0.67: out[r["position"]] = "careless"       # judged on the topic's OTHER questions (this one was wrong)
            else: out[r["position"]] = "concept"
    return out


def why_summary(rows: list[dict], reasons: dict[int, str]) -> list[dict]:
    lost = {}
    for r in rows:
        k = reasons.get(r["position"])
        if k:
            d = lost.setdefault(k, {"reason": k, "label": REASONS[k][0], "advice": REASONS[k][1], "questions": 0, "marks_lost": 0.0})
            d["questions"] += 1; d["marks_lost"] += r["marks"] - r["marks_awarded"]
    return sorted(({**d, "marks_lost": round(d["marks_lost"], 2)} for d in lost.values()), key=lambda d: -d["marks_lost"])


def difficulty_label(correct_rate: float | None, attempts: int | None, min_attempts: int = 20) -> str | None:
    """From what other students actually did; None until enough of them have tried the question."""
    if correct_rate is None or not attempts or attempts < min_attempts:
        return None
    return "easy" if correct_rate >= 0.7 else "hard" if correct_rate < 0.4 else "medium"


def _q(r: dict, exp: float) -> dict:
    return {"position": r["position"], "topic": r["topic"], "time_s": r["time_spent_s"], "expected_s": exp, "outcome": r["outcome"]}
