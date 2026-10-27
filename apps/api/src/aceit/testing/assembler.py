"""Test Factory core (design §8.2, §21.1): build a test from a pool of questions, deterministically from a seed.

Pure code: no database, no clock, no global randomness. The same (pool, blueprint, seed, seen) always gives the
same test, so any test can be reproduced and audited from its seed.

A full mock follows the blueprint: 10 GA questions (5 one-mark, 5 two-mark) and 55 subject questions
(25 one-mark, 30 two-mark), with marks per subject and the MCQ/MSQ/NAT mix inside the ranges seen in real papers.
`validate_plan` is a separate, independent check of the result: a test that fails it is never published.
"""
import random
from dataclasses import dataclass, field


class AssemblyError(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    id: str
    section: str                     # GA | CS
    marks: int                       # 1 | 2
    q_type: str                      # MCQ | MSQ | NAT
    subject: str                     # subject slug ('general-aptitude' for GA)
    topic: str = ""
    dup_group: str = ""              # near-duplicates share a group: at most one per test
    rank_eligible: bool = False


@dataclass
class Plan:
    question_ids: list[str]
    seed: int
    tries: int
    relaxed: bool                    # True = bounds had to be widened: the test must be labelled unranked
    stats: dict = field(default_factory=dict)


def _bounds(bp: dict, widen: int) -> tuple[dict, dict]:
    subj = {s: (max(0, v["min"] - widen), v["max"] + widen) for s, v in bp["subject_marks"].items()}
    types = {t: (max(0, v["min"] - 2 * widen), v["max"] + 2 * widen) for t, v in bp["type_counts_cs"].items()}
    return subj, types


def _allocations(rng, subjects, avail, subj_bounds, target, need_a, need_b):
    """Random walk over (ones, twos) per subject so that totals are need_a and need_b and each subject's marks are in bounds."""
    options = {}
    for s in subjects:
        lo, hi = subj_bounds[s]
        opts = [(a, b) for a in range(avail[s][0] + 1) for b in range(avail[s][1] + 1) if lo <= a + 2 * b <= hi]
        if not opts:
            return None
        rng.shuffle(opts)
        opts.sort(key=lambda o: abs(o[0] + 2 * o[1] - target[s]) + rng.random() * 2)     # near the target, with noise
        options[s] = opts
    order = subjects[:]
    rng.shuffle(order)
    rng_a = {s: (min(o[0] for o in options[s]), max(o[0] for o in options[s])) for s in order}
    rng_b = {s: (min(o[1] for o in options[s]), max(o[1] for o in options[s])) for s in order}
    steps = [0]

    def dfs(i, a_left, b_left):
        steps[0] += 1
        if steps[0] > 20000:
            return None
        if i == len(order):
            return {} if a_left == 0 and b_left == 0 else None
        rest = order[i + 1:]
        for a, b in options[order[i]]:
            na, nb = a_left - a, b_left - b
            if na < sum(rng_a[s][0] for s in rest) or na > sum(rng_a[s][1] for s in rest):
                continue
            if nb < sum(rng_b[s][0] for s in rest) or nb > sum(rng_b[s][1] for s in rest):
                continue
            tail = dfs(i + 1, na, nb)
            if tail is not None:
                tail[order[i]] = (a, b)
                return tail
        return None

    return dfs(0, need_a, need_b)


def _take(rng, cands, n, seen, used_groups):
    """n questions from cands: unseen first, then seen; at most one per near-duplicate group."""
    cands = cands[:]
    rng.shuffle(cands)
    cands.sort(key=lambda c: c.id in seen)                       # stable: unseen come first, still shuffled inside
    out = []
    for c in cands:
        if len(out) == n:
            break
        if c.dup_group and c.dup_group in used_groups:
            continue
        out.append(c)
        if c.dup_group:
            used_groups.add(c.dup_group)
    return out if len(out) == n else None


def build_full_mock(pool: list[Candidate], bp: dict, seed: int, *, seen=frozenset(), rank_only: bool = True,
                    max_tries: int = 200) -> Plan:
    ga_need = (bp["sections"]["GA"]["one_mark"], bp["sections"]["GA"]["two_mark"])
    cs_need = (bp["sections"]["CS"]["one_mark"], bp["sections"]["CS"]["two_mark"])
    usable = [c for c in pool if (c.rank_eligible or not rank_only)]
    ga = [c for c in usable if c.section == "GA"]
    cs = [c for c in usable if c.section == "CS" and c.subject in bp["subject_marks"]]
    subjects = sorted(bp["subject_marks"])
    avail = {s: (sum(1 for c in cs if c.subject == s and c.marks == 1), sum(1 for c in cs if c.subject == s and c.marks == 2)) for s in subjects}
    target = {s: v["target"] for s, v in bp["subject_marks"].items()}
    tries = 0
    for widen, relaxed in ((0, False), (2, True)):
        subj_bounds, type_bounds = _bounds(bp, widen)
        for k in range(max_tries):
            tries += 1
            rng = random.Random(f"{seed}/{widen}/{k}")
            alloc = _allocations(rng, subjects, avail, subj_bounds, target, *cs_need)
            if alloc is None:
                continue
            used: set = set()
            chosen = []
            ok = True
            for part, need in ((ga, ga_need),):
                for m, n in ((1, need[0]), (2, need[1])):
                    got = _take(rng, [c for c in part if c.marks == m], n, seen, used)
                    ok = ok and got is not None
                    chosen += got or []
            for s, (a, b) in alloc.items():
                for m, n in ((1, a), (2, b)):
                    got = _take(rng, [c for c in cs if c.subject == s and c.marks == m], n, seen, used)
                    ok = ok and got is not None
                    chosen += got or []
            if not ok:
                continue
            counts = {t: sum(1 for c in chosen if c.section == "CS" and c.q_type == t) for t in ("MCQ", "MSQ", "NAT")}
            if any(not (type_bounds[t][0] <= counts[t] <= type_bounds[t][1]) for t in type_bounds):
                continue
            ordered = []
            for sec, m in (("GA", 1), ("GA", 2), ("CS", 1), ("CS", 2)):          # GATE order: GA first, 1-mark before 2-mark
                part = [c for c in chosen if c.section == sec and c.marks == m]
                rng.shuffle(part)
                ordered += part
            plan = Plan([c.id for c in ordered], seed, tries, relaxed)
            problems = validate_plan(ordered, bp, rank_only=rank_only, relaxed=relaxed)
            if problems:                                                     # the validator is the judge, not the builder
                continue
            plan.stats = {"type_counts_cs": counts,
                          "subject_marks": {s: sum(c.marks for c in ordered if c.subject == s) for s in subjects},
                          "seen_reused": sum(1 for c in ordered if c.id in seen)}
            return plan
    raise AssemblyError(f"could not build a valid test from {len(usable)} usable questions after {tries} tries")


def build_pair(pool: list[Candidate], bp: dict, seed: int, *, seen=frozenset(), rank_only: bool = True) -> tuple[Plan, Plan]:
    """Two full mocks from the same blueprint with no question in common (like GATE's CS1 and CS2 sittings).
    Set 1 is built first; set 2 only from what is left. All or nothing: if either cannot be built, AssemblyError."""
    one = build_full_mock(pool, bp, seed, seen=seen, rank_only=rank_only)
    used = set(one.question_ids)
    two = build_full_mock([c for c in pool if c.id not in used], bp, seed + 1, seen=seen, rank_only=rank_only)
    return one, two


def validate_plan(questions: list[Candidate], bp: dict, *, rank_only: bool, relaxed: bool = False) -> list[str]:
    """Independent check of a finished test. Returns the list of problems (empty = valid)."""
    p = []
    ids = [q.id for q in questions]
    if len(ids) != bp["total_questions"]:
        p.append(f"{len(ids)} questions, expected {bp['total_questions']}")
    if len(set(ids)) != len(ids):
        p.append("a question appears twice")
    groups = [q.dup_group for q in questions if q.dup_group]
    if len(set(groups)) != len(groups):
        p.append("two near-duplicate questions in one test")
    if sum(q.marks for q in questions) != bp["total_marks"]:
        p.append(f"marks add up to {sum(q.marks for q in questions)}, expected {bp['total_marks']}")
    for sec, spec in bp["sections"].items():
        part = [q for q in questions if q.section == sec]
        if (len(part), sum(1 for q in part if q.marks == 1), sum(1 for q in part if q.marks == 2)) != (spec["questions"], spec["one_mark"], spec["two_mark"]):
            p.append(f"section {sec} is not {spec['one_mark']}x1 + {spec['two_mark']}x2 marks")
    if rank_only and any(not q.rank_eligible for q in questions):
        p.append("a question that is not rank-eligible in a rank test")
    subj, types = _bounds(bp, 2 if relaxed else 0)
    for s, (lo, hi) in subj.items():
        m = sum(q.marks for q in questions if q.section == "CS" and q.subject == s)
        if not lo <= m <= hi:
            p.append(f"subject {s} has {m} marks, allowed {lo}-{hi}")
    for t, (lo, hi) in types.items():
        n = sum(1 for q in questions if q.section == "CS" and q.q_type == t)
        if not lo <= n <= hi:
            p.append(f"{n} {t} questions, allowed {lo}-{hi}")
    if any(q.section == "CS" and q.subject not in bp["subject_marks"] for q in questions):
        p.append("a question from outside the syllabus")
    return p


def build_topic_test(pool: list[Candidate], topics: set[str], n: int, seed: int, *, seen=frozenset(),
                     rank_only: bool = False, min_per_type: dict | None = None) -> list[str]:
    """n questions on the given topic or subject slugs (a topic matches itself and everything under it)."""
    match = lambda c: any(c.topic == t or c.topic.startswith(t + "/") or c.subject == t for t in topics)
    cands = [c for c in pool if match(c) and (c.rank_eligible or not rank_only)]
    rng = random.Random(f"topic/{seed}")
    got = _take(rng, cands, min(n, len(cands)), seen, set())
    if got is None or not got:
        raise AssemblyError("no questions for these topics")
    rng.shuffle(got)
    return [c.id for c in got]
