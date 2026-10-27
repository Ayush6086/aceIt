#!/usr/bin/env python3
"""Derive the GATE CS exam blueprint and a small development question pool from the real data.

    python3 tools/derive_blueprint.py --keys-dir ~/Downloads/GATE/pyq

Writes
  data/blueprints/gate_cs_v1.json         how a paper is built: question counts, marks per subject (target/min/max), type mix
  data/pool/gate_cs_dev_pool.json         one row per question (id, section, marks, type, subject, topic): fixtures for tests
Marks and types come from the official keys, subjects from the topic tags (data/tags). Only the recent format
(2018 and 2022-2026: 9 sittings) sets the blueprint ranges, because 2013-2014 used different formats.
2013 booklets B-D are left out of the pool: they repeat booklet A's questions in another order.
"""
import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import import_keys as ik
import load_tags as lt

ROOT = Path(__file__).resolve().parent.parent
BLUEPRINT_YEARS = {2018, 2022, 2023, 2024, 2025, 2026}
TYPE_YEARS = {2022, 2023, 2024, 2025, 2026}               # MSQ and NAT in today's proportions
RANK_EXAMPLE = {"2024_CS1", "2024_CS2", "2016_CS1", "2016_CS2"}      # sittings whose key is confirmed final


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keys-dir", required=True, type=Path)
    args = ap.parse_args()

    by_name, subject_of = lt.taxonomy_index()
    tags = {}
    for path in sorted((ROOT / "data" / "tags").glob("gate_cs_*.txt")):
        tags.update(lt.parse(path.read_text()))

    pool, subj_marks, type_counts, finality = [], defaultdict(list), defaultdict(list), {}
    for e in ik.MANIFEST:
        label = f"{e.year}_{e.sitting}"
        if label not in tags:
            continue                                          # keys we have but papers not yet ingested (2017, 2019, 2020)
        parsed = ik.parse_file(e, args.keys_dir)
        if ik.validate(parsed):
            print(f"key file for {label} does not validate", file=sys.stderr)
            return 1
        finality[label] = parsed["finality"]
        rows = {r["number"]: r for r in parsed["rows"]}
        t = {r["number"]: r for r in tags[label]}
        marks_by_subject, types = defaultdict(int), defaultdict(int)
        for n, k in rows.items():
            prim = lt.resolve(t[n]["primary"], by_name)
            subject = subject_of[prim]
            ga = k["section"] == "GA"
            if e.year == 2013 and e.sitting != "CS-A":
                pass                                          # same questions as booklet A: not added to the pool
            else:
                pool.append(dict(id=f"{label}_Q{n}", sitting=label, year=e.year, number=n, section="GA" if ga else "CS",
                                 marks=k["marks"], type=k["q_type"], subject=subject, topic=prim, key_type=k["key_type"],
                                 low_confidence=bool(t[n]["low"]), rank_eligible=(label in RANK_EXAMPLE)))
            if not ga:
                marks_by_subject[subject] += k["marks"]
                types[k["q_type"]] += 1
        if e.year in BLUEPRINT_YEARS:
            for s in {subject_of[lt.resolve(x["primary"], by_name)] for x in tags[label]} - {"general-aptitude"}:
                subj_marks[s].append(marks_by_subject.get(s, 0))
        if e.year in TYPE_YEARS:
            for ty in ("MCQ", "MSQ", "NAT"):
                type_counts[ty].append(types.get(ty, 0))

    subjects = {s: {"target": round(statistics.mean(v), 1), "min": min(v), "max": max(v)} for s, v in sorted(subj_marks.items())
                if s != "out-of-current-syllabus"}
    bp = {
        "version": "gate-cs-v1", "paper": "CS", "duration_min": 180, "total_questions": 65, "total_marks": 100,
        "sections": {"GA": {"questions": 10, "one_mark": 5, "two_mark": 5, "marks": 15},
                     "CS": {"questions": 55, "one_mark": 25, "two_mark": 30, "marks": 85}},
        "marking": {"mcq_negative_fraction": "1/3", "msq": "all-or-nothing, no negative", "nat": "range, no negative"},
        "subject_marks": subjects,
        "type_counts_cs": {ty: {"target": round(statistics.mean(v), 1), "min": min(v), "max": max(v)} for ty, v in type_counts.items()},
        "derived_from": f"{len(BLUEPRINT_YEARS)} paper years (2018, 2022-2026), topic tags are bootstrap labels",
    }
    (ROOT / "data" / "blueprints").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "pool").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "blueprints" / "gate_cs_v1.json").write_text(json.dumps(bp, indent=2) + "\n")
    (ROOT / "data" / "pool" / "gate_cs_dev_pool.json").write_text(json.dumps(pool, separators=(",", ":")) + "\n")
    print(json.dumps({k: bp[k] for k in ("subject_marks", "type_counts_cs")}, indent=1))
    print(f"pool: {len(pool)} questions; rank-eligible example sittings: {sorted(RANK_EXAMPLE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
