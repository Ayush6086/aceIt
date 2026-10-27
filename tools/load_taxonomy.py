#!/usr/bin/env python3
"""Turn data/taxonomy/gate_cs.json into SQL for the `topic` and `topic_alias` tables.

    python3 tools/load_taxonomy.py --syllabus ~/Downloads/GATE/CS_GATE2027_Syllabus.pdf > taxonomy.sql
    psql -d aceit -f taxonomy.sql

Checks (any failure = no SQL):
  1. every topic name that is not marked `derived` / non-syllabus appears in the syllabus PDF text;
  2. every meaningful word of the syllabus is covered by some topic name (nothing silently dropped);
  3. aliases are unique across the whole paper (a student's word must mean one thing).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "taxonomy" / "gate_cs.json"
STOP = set("and of the in to a an for on with by or e g section gate iit madras organizing institute cs computer science "
           "information technology".split())


def norm(s: str) -> str:
    """lowercase, every dash/punctuation -> space, collapse spaces. 'divide-and-conquer' == 'divide and conquer'."""
    s = re.sub(r"[^a-z0-9+]+", " ", s.lower())
    return " ".join(s.split())


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def walk(tax: dict):
    """Yield (path_slugs, level, node, parent_slug_path)."""
    for si, subj in enumerate(tax["subjects"]):
        sp = slugify(subj["name"])
        yield (sp,), 1, subj, None, si
        for ti, top in enumerate(subj["topics"]):
            tp = f"{sp}/{slugify(top['name'])}"
            yield (tp,), 2, top, sp, ti
            for ui, sub in enumerate(top.get("subtopics", [])):
                yield (f"{tp}/{slugify(sub['name'])}",), 3, sub, tp, ui


def check(tax: dict, syllabus_text: str) -> list[str]:
    errs, syl = [], norm(syllabus_text)
    seen_slug, seen_alias = {}, {}
    covered = set()
    for (slug,), level, node, _, _ in walk(tax):
        slug = slug
        if slug in seen_slug:
            errs.append(f"duplicate slug {slug}")
        seen_slug[slug] = node["name"]
        from_syllabus = not node.get("derived") and node.get("source", "syllabus") == "syllabus"
        # a subject inherits its source from its topics
        if level == 1:
            from_syllabus = all(t.get("source", "syllabus") == "syllabus" for t in node["topics"])
        if from_syllabus:
            if f" {norm(node['name'])} " not in f" {syl} ":
                errs.append(f"'{node['name']}' is not in the syllabus text")
            covered |= set(norm(node["name"]).split())
        for a in set(node.get("aliases", [])) | {node["name"]}:
            key = norm(a)
            if key in seen_alias and seen_alias[key] != slug:
                errs.append(f"alias '{a}' used by both {seen_alias[key]} and {slug}")
            seen_alias[key] = slug
    missing = sorted({w for w in syl.split() if w not in STOP and not w.isdigit()} - covered)
    if missing:
        errs.append(f"syllabus words not covered by any topic name: {missing}")
    return errs


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def emit(tax: dict) -> str:
    paper = f"(SELECT id FROM paper WHERE code = {q(tax['paper'])})"
    out = ["BEGIN;"]
    for (slug,), level, node, parent, sort in walk(tax):
        src = node.get("source", "syllabus")
        parent_sql = f"(SELECT id FROM topic WHERE paper_id = {paper} AND slug = {q(parent)})" if parent else "NULL"
        out.append(f"INSERT INTO topic (paper_id, parent_id, slug, name, level, sort, syllabus, source, derived) VALUES "
                   f"({paper}, {parent_sql}, {q(slug)}, {q(node['name'])}, {level}, {sort}, {q(tax['syllabus'])}, {q(src)}, {str(bool(node.get('derived'))).lower()});")
        aliases = {norm(a): a for a in node.get("aliases", [])}
        aliases.setdefault(norm(node["name"]), node["name"])
        for key in sorted(aliases):
            out.append(f"INSERT INTO topic_alias (topic_id, alias, source) SELECT id, {q(key)}, 'seed' FROM topic WHERE paper_id = {paper} AND slug = {q(slug)};")
    out.append("COMMIT;")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--syllabus", required=True, type=Path)
    args = ap.parse_args()
    tax = json.loads(DATA.read_text())
    text = subprocess.run(["pdftotext", "-layout", str(args.syllabus), "-"], capture_output=True, text=True, check=True).stdout
    errs = check(tax, text)
    nodes = list(walk(tax))
    n = lambda lv: sum(1 for x in nodes if x[1] == lv)
    print(f"{n(1)} subjects, {n(2)} topics, {n(3)} subtopics; "
          f"{sum(len(set(x[2].get('aliases', [])) | {x[2]['name']}) for x in nodes)} alias entries", file=sys.stderr)
    if errs:
        for e in errs:
            print(f"  REFUSED: {e}", file=sys.stderr)
        return 1
    print("syllabus check OK: every name is in the PDF, every syllabus word is covered, aliases are unique", file=sys.stderr)
    print(emit(tax))
    return 0


if __name__ == "__main__":
    sys.exit(main())
