"""Score a whole attempt: totals, per-section and per-topic breakdown, and counts."""
from collections import defaultdict
from dataclasses import dataclass, field
from fractions import Fraction

from .marks import score_question


@dataclass(frozen=True)
class Item:
    """One question as it was asked in an attempt."""
    question_id: str
    section: str                    # GA | CS
    q_type: str                     # MCQ | MSQ | NAT
    marks: int
    key_type: str
    key: dict | None
    topic: str | None               # primary topic slug, for the topic breakdown
    response: dict | None = None
    time_spent_s: int = 0


@dataclass
class AttemptResult:
    score: Fraction
    max_score: Fraction
    by_section: dict
    by_topic: dict
    counts: dict
    per_question: list = field(default_factory=list)

    def as_json(self) -> dict:
        f = lambda x: round(float(x), 2)
        return {"score": f(self.score), "max_score": f(self.max_score),
                "by_section": {k: {"score": f(v[0]), "max": f(v[1])} for k, v in self.by_section.items()},
                "by_topic": {k: {"score": f(v[0]), "max": f(v[1]), "correct": v[2], "wrong": v[3], "unattempted": v[4]} for k, v in self.by_topic.items()},
                "counts": self.counts}


def score_attempt(items: list[Item], scheme: dict | None = None) -> AttemptResult:
    sec = defaultdict(lambda: [Fraction(0), Fraction(0)])
    top = defaultdict(lambda: [Fraction(0), Fraction(0), 0, 0, 0])
    counts = defaultdict(int)
    per_q, total, best = [], Fraction(0), Fraction(0)
    for it in items:
        o = score_question(it.q_type, it.marks, it.key_type, it.key, it.response, scheme)
        total += o.marks
        best += o.max_marks
        sec[it.section][0] += o.marks
        sec[it.section][1] += o.max_marks
        counts[o.status] += 1
        if it.topic and o.status != "not_scored":
            t = top[it.topic]
            t[0] += o.marks
            t[1] += o.max_marks
            t[2 + {"correct": 0, "awarded_to_all": 0, "wrong": 1}.get(o.status, 2)] += 1
        per_q.append((it.question_id, o))
    return AttemptResult(total, best, {k: tuple(v) for k, v in sec.items()}, {k: tuple(v) for k, v in top.items()}, dict(counts), per_q)
