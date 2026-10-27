"""Marking rules for one question. Pure functions, exact arithmetic (no floats until the very end).

GATE rules (design doc §2), overridable per paper in `scheme`:
  MCQ  right = +marks, wrong = -marks/3 (so -1/3 for a 1-mark and -2/3 for a 2-mark question), unanswered = 0
  MSQ  the exact set of correct options = +marks, anything else = 0 (no partial marks, no negative marks)
  NAT  a value inside the official range (ends included) = +marks, anything else = 0 (no negative marks)
  MTA  "marks to all": every candidate gets the marks, answered or not
  dropped questions are not scored at all
A key may accept several answers: {"any_of": [ {...}, {...} ]}.
"""
from dataclasses import dataclass
from fractions import Fraction

DEFAULT_SCHEME = {"mcq_negative_fraction": Fraction(1, 3)}      # of the question's marks


@dataclass(frozen=True)
class Outcome:
    marks: Fraction                 # awarded, may be negative
    status: str                     # correct | wrong | unattempted | awarded_to_all | not_scored
    max_marks: Fraction             # what the question is worth in the total (0 if not scored)


def _num(x) -> Fraction:
    return Fraction(str(x))         # str() so 0.1 stays 1/10, not the binary float value


def _matches(q_type: str, key: dict, response) -> bool:
    if "any_of" in key:
        return any(_matches(q_type, k, response) for k in key["any_of"])
    if q_type == "MCQ":
        return response.get("choice") == key["choice"]
    if q_type == "MSQ":
        return sorted(set(response.get("choices", []))) == sorted(set(key["choices"]))
    if q_type == "NAT":
        value = response.get("value")
        if value is None:
            return False
        try:
            return _num(key["min"]) <= _num(value) <= _num(key["max"])
        except (ValueError, ArithmeticError):
            return False
    raise ValueError(f"unknown question type {q_type!r}")


def is_answered(q_type: str, response) -> bool:
    if not response:
        return False
    if q_type == "MCQ":
        return bool(response.get("choice"))
    if q_type == "MSQ":
        return bool(response.get("choices"))
    if q_type == "NAT":
        v = response.get("value")
        return v is not None and str(v).strip() != ""
    raise ValueError(q_type)


def score_question(q_type: str, marks: int, key_type: str, key: dict | None, response, scheme: dict | None = None) -> Outcome:
    """key_type: mcq | msq | nat | mta | dropped (as stored in question_key)."""
    scheme = {**DEFAULT_SCHEME, **(scheme or {})}
    worth = Fraction(marks)
    if key_type == "dropped":
        return Outcome(Fraction(0), "not_scored", Fraction(0))
    if key_type == "mta":
        return Outcome(worth, "awarded_to_all", worth)
    if not is_answered(q_type, response):
        return Outcome(Fraction(0), "unattempted", worth)
    if _matches(q_type, key, response):
        return Outcome(worth, "correct", worth)
    if q_type == "MCQ":
        return Outcome(-worth * scheme["mcq_negative_fraction"], "wrong", worth)
    return Outcome(Fraction(0), "wrong", worth)
