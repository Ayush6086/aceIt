#!/usr/bin/env python3
"""Carry the topic tags of GATE 2013 booklet A over to booklets B, C and D.

The four 2013 booklets hold the SAME 65 questions in a different order, so each question is tagged once (booklet A)
and the other three booklets get the same tags through a verified match on the question text.

    psql -d aceit -At -c "<export>" > questions.jsonl      # one JSON object per question (id, type, m, stem, opts)
    python3 tools/map_booklets.py --questions questions.jsonl --tags data/tags/gate_cs_2013_2018.txt [--write]

Matching: words are weighted by how rare they are among booklet A's questions (the shared "Common Data" blocks of
paired questions would otherwise make 48/49, 50/51, 52/53, 54/55 look identical), then questions are paired
one-to-one, best match first. Every pairing is verified: same marks, same question type, similarity at least
MIN_SIM. Anything that fails is reported and NOTHING is written.
"""
import argparse
import collections
import json
import math
import re
import sys
from pathlib import Path

MIN_SIM = 0.5
LOW = 0.7                       # a verified match below this is carried over as a low-confidence ('?') tag


def words(r: dict) -> set:
    toks = lambda s: set(re.findall(r"[A-Za-z0-9]{3,}", (s or "").lower()))
    return toks(r["stem"]) | {"opt:" + t for t in toks(r.get("opts"))}


def similarity(a: set, b: set, idf: dict) -> float:
    """Average of Jaccard and containment. Containment tolerates stray page-header text stuck onto one side."""
    w = lambda s: sum(idf.get(t, 1.0) for t in s)
    inter, union, small = w(a & b), w(a | b), min(w(a), w(b))
    if not union or not small:
        return 0.0
    return 0.5 * (inter / union) + 0.5 * (inter / small)


def match(book_a: dict, book_x: dict) -> tuple[dict, list[str]]:
    """-> ({slot in X: slot in A}, problems)."""
    sig_a = {n: words(r) for n, r in book_a.items()}
    df = collections.Counter(t for s in sig_a.values() for t in s)
    idf = {t: 1.0 / c for t, c in df.items()}           # a word found in several questions counts for less
    sig_x = {n: words(r) for n, r in book_x.items()}
    pairs = sorted(((similarity(sx, sa, idf), x, a) for x, sx in sig_x.items() for a, sa in sig_a.items()), reverse=True)
    out, used_a, sims = {}, set(), {}
    for s, x, a in pairs:
        if x not in out and a not in used_a:
            out[x], sims[x] = a, s
            used_a.add(a)
    problems = []
    if len(out) != len(book_a) or len(out) != len(book_x):
        problems.append(f"matched {len(out)} of {len(book_x)} questions")
    for x, a in out.items():
        ra, rx = book_a[a], book_x[x]
        if ra["m"] != rx["m"] or ra["type"] != rx["type"]:
            problems.append(f"Q{x} -> A{a}: marks/type differ ({rx['m']} {rx['type']} vs {ra['m']} {ra['type']})")
        if sims[x] < MIN_SIM:
            problems.append(f"Q{x} -> A{a}: similarity only {sims[x]:.2f}")
    return {x: (a, sims[x]) for x, a in out.items()}, problems


def read_tags(path: Path) -> dict:
    """{label: {slot: tag-text}} where tag-text is everything after the number on the tag line."""
    out, cur = {}, None
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = {}
        elif cur and re.match(r"^\d+\s", line):
            n, rest = line.split(None, 1)
            out[cur][int(n)] = rest.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", required=True, type=Path)
    ap.add_argument("--tags", required=True, type=Path)
    ap.add_argument("--write", action="store_true", help="append the B-D sections to the tag file")
    args = ap.parse_args()

    books = collections.defaultdict(dict)
    for line in args.questions.read_text().splitlines():
        r = json.loads(line)
        m = re.match(r"2013_CS-([A-D])_Q(\d+)$", r["id"])
        if m:
            books[m.group(1)][int(m.group(2))] = r
    tags = read_tags(args.tags)
    tags_a = tags.get("2013_CS-A", {})
    if sorted(tags_a) != list(range(1, 66)):
        print("booklet A is not fully tagged (need 1..65)", file=sys.stderr)
        return 1

    sections, failed = [], False
    for b in "BCD":
        label = f"2013_CS-{b}"
        if label in tags:
            print(f"{label}: already tagged, skipped", file=sys.stderr)
            continue
        mapping, problems = match(books["A"], books[b])
        sims = [s for _, s in mapping.values()]
        print(f"{label}: {len(mapping)} matched, mean similarity {sum(sims)/len(sims):.2f}, "
              f"lowest {min(sims):.2f}, {sum(1 for s in sims if s < LOW)} below {LOW}", file=sys.stderr)
        for p in problems:
            print(f"   - {p}", file=sys.stderr)
        if problems:
            failed = True
            continue
        lines = [f"## {label}"]
        for x in range(1, 66):
            a, s = mapping[x]
            tag = tags_a[a]
            if s < LOW and not tag.endswith("?"):
                tag += " ?"
            lines.append(f"{x} {tag}")
        sections.append("\n".join(lines))
    if failed:
        print("Nothing written.", file=sys.stderr)
        return 1
    if args.write and sections:
        with args.tags.open("a") as f:
            f.write("\n".join(sections) + "\n")
        print(f"wrote {len(sections)} booklet(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
