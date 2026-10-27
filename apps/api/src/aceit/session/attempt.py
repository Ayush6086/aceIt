"""Timed attempt rules (design §10, §21.2). Pure code: the caller passes `now`, so every rule is testable.

  * The SERVER owns time: the deadline is fixed when the attempt starts. A client clock is only ever a display.
  * Autosave is idempotent: each batch carries a client_seq; replays and out-of-order batches are ignored safely.
  * A save is accepted until deadline + GRACE seconds (so the last batch of a student on a slow link still counts).
  * Submit is idempotent. An attempt abandoned past deadline + GRACE is closed by the sweeper, as 'auto_submitted'.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

GRACE_S = 30
STATUSES = ("in_progress", "submitted", "auto_submitted", "excluded")
PALETTE = ("not_visited", "not_answered", "answered", "marked", "answered_marked")


@dataclass
class Response:
    response: dict | None = None
    palette_status: str = "not_visited"
    time_spent_s: int = 0


@dataclass
class Attempt:
    id: str
    user_id: str
    started_at: datetime
    deadline_at: datetime
    status: str = "in_progress"
    submitted_at: datetime | None = None
    last_seq: int = -1
    responses: dict = field(default_factory=dict)            # question_version_id -> Response
    integrity: dict = field(default_factory=lambda: {"tab_blur": 0, "fullscreen_exit": 0, "second_session": 0})


def start_attempt(attempt_id: str, user_id: str, now: datetime, duration_s: int, time_multiplier: float = 1.0) -> Attempt:
    """time_multiplier > 1 is the extra time granted to candidates with a disability (design §18)."""
    if duration_s <= 0 or time_multiplier < 1:
        raise ValueError("duration must be positive and the multiplier at least 1")
    return Attempt(attempt_id, user_id, now, now + timedelta(seconds=round(duration_s * time_multiplier)))


def remaining_s(a: Attempt, now: datetime) -> int:
    return max(0, int((a.deadline_at - now).total_seconds()))


def is_open(a: Attempt, now: datetime) -> bool:
    return a.status == "in_progress" and now <= a.deadline_at + timedelta(seconds=GRACE_S)


def apply_autosave(a: Attempt, batch: list[dict], seq: int, now: datetime, allowed_questions: set | None = None) -> dict:
    """batch items: {question_id, response, palette_status, time_spent_s}. Returns {accepted, reason, remaining_s}."""
    out = lambda ok, why: {"accepted": ok, "reason": why, "remaining_s": remaining_s(a, now), "status": a.status}
    if a.status != "in_progress":
        return out(False, "attempt_closed")
    if not is_open(a, now):
        return out(False, "too_late")
    if seq <= a.last_seq:
        return out(True, "duplicate")                       # a retry of something already applied: acknowledge, change nothing
    elapsed = int((now - a.started_at).total_seconds())
    for item in batch:
        qid = item["question_id"]
        if allowed_questions is not None and qid not in allowed_questions:
            return out(False, "unknown_question")
        status = item.get("palette_status", "not_answered")
        if status not in PALETTE:
            return out(False, "bad_palette_status")
    for item in batch:
        cur = a.responses.setdefault(item["question_id"], Response())
        cur.response = item.get("response")
        cur.palette_status = item.get("palette_status", cur.palette_status)
        # time spent only grows, and can never exceed the time since the attempt started
        cur.time_spent_s = min(max(cur.time_spent_s, int(item.get("time_spent_s", 0))), elapsed)
    a.last_seq = seq
    return out(True, "ok")


def submit(a: Attempt, now: datetime) -> str:
    """Idempotent. Returns the final status."""
    if a.status != "in_progress":
        return a.status
    a.status = "submitted" if now <= a.deadline_at + timedelta(seconds=GRACE_S) else "auto_submitted"
    a.submitted_at = min(now, a.deadline_at)                 # time spent never counts past the deadline
    return a.status


def sweep(attempts: list[Attempt], now: datetime) -> list[Attempt]:
    """Close every attempt left open past deadline + grace. Returns the ones that were closed."""
    closed = []
    for a in attempts:
        if a.status == "in_progress" and now > a.deadline_at + timedelta(seconds=GRACE_S):
            a.status, a.submitted_at = "auto_submitted", a.deadline_at
            closed.append(a)
    return closed


def integrity_excludes_from_cohort(a: Attempt) -> bool:
    """No proctor: severe anomalies only remove the attempt from rank and cohort statistics. The student still sees
    their own result and nothing is punitive (design §21.2)."""
    i = a.integrity
    return i["second_session"] >= 1 or i["tab_blur"] >= 15 or i["fullscreen_exit"] >= 10
