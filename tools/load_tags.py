#!/usr/bin/env python3
"""Load question topic tags (data/tags/*.txt) into the question_topic table.

    python3 tools/load_tags.py --key-json keys.json > tags.sql     # keys.json from tools/import_keys.py --dump-json
    psql -d aceit -f tags.sql                                      # after the questions are ingested

Tag file format (one sitting per '## <year>_<sitting>' block):
    <question number> <topic> [+ <second topic>] [?]
  topic = last path segment of a slug in data/taxonomy/gate_cs.json at ANY level (e.g. deadlock, dynamic-programming),
          or a subject slug (e.g. algorithms) when no specific topic of that subject fits.
  '?'   = lower confidence.

Refuses (no SQL) when: a name is unknown or ambiguous; a sitting does not have exactly questions 1..65 once each;
a General Aptitude question has a non-aptitude tag or the reverse (section comes from the official key).
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY = ROOT / "data" / "taxonomy" / "gate_cs.json"
SOURCE = "claude-bootstrap"
CONF = {False: 0.9, True: 0.5}            # '?' halves the confidence; a second topic is 0.1 lower


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def taxonomy_index() -> tuple[dict[str, list[str]], dict[str, str]]:
    """-> ({last-segment: [full slugs]}, {full slug: subject slug})."""
    tax = json.loads(TAXONOMY.read_text())
    by_name, subject_of = defaultdict(list), {}
    for subj in tax["subjects"]:
        sp = slugify(subj["name"])
        by_name[sp].append(sp)
        subject_of[sp] = sp
        for top in subj["topics"]:
            tp = f"{sp}/{slugify(top['name'])}"
            by_name[slugify(top["name"])].append(tp)
            subject_of[tp] = sp
            for sub in top.get("subtopics", []):
                full = f"{tp}/{slugify(sub['name'])}"
                by_name[slugify(sub["name"])].append(full)
                subject_of[full] = sp
    return by_name, subject_of


def parse(text: str) -> dict[str, list[dict]]:
    sittings, cur = {}, None
    for ln, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or (line.startswith("#") and not line.startswith("##")):
            continue
        if line.startswith("##"):
            cur = line[2:].strip()
            sittings[cur] = []
            continue
        m = re.fullmatch(r"(\d+)\s+(\S+)(?:\s*\+\s*(\S+))?(\s*\?)?", line)
        if not m or cur is None:
            raise ValueError(f"line {ln}: cannot read {line!r}")
        sittings[cur].append(dict(number=int(m.group(1)), primary=m.group(2), second=m.group(3), low=bool(m.group(4)), line=ln))
    return sittings


def resolve(name: str, by_name) -> str:
    hits = by_name.get(name, [])
    if len(hits) != 1:
        raise ValueError(f"'{name}' " + ("is not a topic" if not hits else f"is ambiguous: {hits}"))
    return hits[0]


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tags", type=Path, nargs="+", default=sorted((ROOT / "data" / "tags").glob("gate_cs_*.txt")),
                    help="tag files (default: every data/tags/gate_cs_*.txt)")
    ap.add_argument("--key-json", required=True, type=Path)
    args = ap.parse_args()
    by_name, subject_of = taxonomy_index()
    keys = json.loads(args.key_json.read_text())
    sittings = {}
    for path in args.tags:
        for label, rows in parse(path.read_text()).items():
            if label in sittings:
                print(f"  REFUSED: {label} is tagged in more than one file", file=sys.stderr)
                return 1
            sittings[label] = rows

    errs, sql = [], ["BEGIN;"]
    stats = {}
    for label, rows in sittings.items():
        year, sitting = label.split("_", 1)
        key = {r["number"]: r for r in keys[label]}
        nums = sorted(r["number"] for r in rows)
        if nums != list(range(1, 66)):
            errs.append(f"{label}: tagged questions are not exactly 1..65 once each ({len(nums)} lines)")
        marks, low, sec = defaultdict(int), 0, 0
        for r in rows:
            try:
                prim = resolve(r["primary"], by_name)
                second = resolve(r["second"], by_name) if r["second"] else None
            except ValueError as e:
                errs.append(f"{label} Q{r['number']} (line {r['line']}): {e}")
                continue
            k = key.get(r["number"])
            if not k:
                errs.append(f"{label} Q{r['number']}: no such question in the key")
                continue
            is_ga = k["section"] == "GA"
            for t in filter(None, (prim, second)):
                if (subject_of[t] == "general-aptitude") != is_ga:
                    errs.append(f"{label} Q{r['number']}: {'aptitude' if is_ga else 'subject'} question tagged '{t}' of the other kind")
            marks[subject_of[prim]] += k["marks"]
            low += r["low"]
            sec += second is not None
            lookup = (f"(SELECT q.id FROM question q JOIN paper_session ps ON ps.id = q.session_id JOIN paper p ON p.id = ps.paper_id "
                      f"WHERE p.code = 'CS' AND ps.year = {year} AND ps.session_code = {q(sitting)} AND q.number = {r['number']} AND q.origin = 'official_pyq')")
            for topic, primary, conf in ((prim, True, CONF[r["low"]]), (second, False, CONF[r["low"]] - 0.1)):
                if topic:
                    sql.append(f"INSERT INTO question_topic (question_id, topic_id, is_primary, confidence, source) "
                               f"SELECT {lookup}, t.id, {str(primary).lower()}, {conf:.1f}, {q(SOURCE)} FROM topic t "
                               f"JOIN paper p ON p.id = t.paper_id WHERE p.code = 'CS' AND t.slug = {q(topic)};")
        stats[label] = (dict(marks), low, sec)
    sql.append("COMMIT;")

    subjects = ["general-aptitude", "engineering-mathematics", "digital-logic", "computer-organization-and-architecture",
                "programming-and-data-structures", "algorithms", "theory-of-computation", "compiler-design",
                "operating-system", "databases", "computer-networks"]
    short = ["GA", "Math", "DL", "COA", "PDS", "Algo", "TOC", "CD", "OS", "DB", "CN"]
    print(f"{'sitting':<10}" + "".join(f"{s:>6}" for s in short) + f"{'total':>7}{'low?':>6}{'2nd':>5}   (marks per primary subject)", file=sys.stderr)
    for label, (marks, low, sec) in stats.items():
        print(f"{label:<10}" + "".join(f"{marks.get(s, 0):>6}" for s in subjects) + f"{sum(marks.values()):>7}{low:>6}{sec:>5}", file=sys.stderr)
    if errs:
        for e in errs[:40]:
            print(f"  REFUSED: {e}", file=sys.stderr)
        print(f"{len(errs)} problem(s). Nothing written.", file=sys.stderr)
        return 1
    print("\n".join(sql))
    return 0


if __name__ == "__main__":
    sys.exit(main())
