"""Cohort percentile and the predicted-score band. Pure code; both are labelled as estimates wherever they are shown."""
import math

MIN_COHORT = 30                       # below this the percentile is shown as low-confidence
MIN_QUESTIONS_FOR_PREDICTION = 60     # about one full paper of evidence
PRIOR_MARKS, PRIOR_RATE = 4, 0.25     # a pinch of prior so a topic seen once does not read as 0% or 100%


def percentile(score: float, others: list[float]) -> dict | None:
    """Share of the cohort this score beats (ties count half). `others` are the other students' scores on rank-bearing tests."""
    n = len(others)
    if n == 0:
        return None
    below = sum(1 for s in others if s < score) + 0.5 * sum(1 for s in others if s == score)
    return {"percentile": round(100 * below / n, 1), "cohort_size": n, "confidence": "ok" if n >= MIN_COHORT else "low",
            "rank_estimate": 1 + sum(1 for s in others if s > score)}


def predicted_band(subject_stats: dict, blueprint: dict) -> dict | None:
    """subject_stats: {subject slug: {"earned": marks, "possible": marks, "questions": n}} over everything the student has done.
    Expected marks = sum over subjects of (the blueprint's marks for the subject x the student's smoothed score rate there).
    The band is about an 80% interval from how little evidence each subject has. A heuristic, not a promise."""
    total_q = sum(s["questions"] for s in subject_stats.values())
    if total_q < MIN_QUESTIONS_FOR_PREDICTION:
        return None
    weights = {s: v["target"] for s, v in blueprint["subject_marks"].items()}
    weights["general-aptitude"] = blueprint["sections"]["GA"]["marks"]
    mid, var = 0.0, 0.0
    for subj, w in weights.items():
        st = subject_stats.get(subj, {"earned": 0.0, "possible": 0.0, "questions": 0})
        rate = (st["earned"] + PRIOR_MARKS * PRIOR_RATE) / (st["possible"] + PRIOR_MARKS)
        rate = min(1.0, max(0.0, rate))
        mid += w * rate
        var += (w ** 2) * rate * (1 - rate) / (st["questions"] + 2)
    sd = math.sqrt(var)
    return {"low": round(max(0.0, mid - 1.28 * sd), 1), "mid": round(mid, 1), "high": round(min(100.0, mid + 1.28 * sd), 1),
            "based_on_questions": total_q, "note": "An estimate from your practice so far, not a prediction of the real result."}
