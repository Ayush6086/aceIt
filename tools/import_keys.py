#!/usr/bin/env python3
"""Parse official GATE CS answer-key PDFs into SQL for db/schema.sql (table official_key_entry).

    python3 tools/import_keys.py --keys-dir ~/Downloads/GATE/pyq > keys.sql
    psql -d aceit -f keys.sql

Needs `pdftotext` (poppler). No other dependencies.

It is strict on purpose: a key file that does not add up (65 questions, 100 marks, 10 GA questions,
every key readable) is REFUSED, not half-imported. The report goes to stderr, the SQL to stdout,
so a refusal never produces SQL.

Layouts handled (each organiser formatted its key differently):
  rows     one row per question:  [Q.No] [Session] Type Section Key Marks         (2016-2026)
           Q.No may restart for the CS section (2018-2020) or list GA last (2017).
  twocol   two answer tables side by side, no Type column                          (2014)
  ors      one column of keys per ORS paper code A-D, no Type or Marks column      (2013)
Not handled (the key is an image or a scan, needs OCR): 2015, 2021.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

EXPECTED_QUESTIONS, EXPECTED_MARKS, EXPECTED_GA = 65, 100, 10


@dataclass
class Entry:
    year: int
    sitting: str
    path: str            # relative to --keys-dir
    style: str           # rows | twocol | ors
    ors: str = ""        # ORS code for style=ors
    finality: str = ""   # override when the SOURCE says final (e.g. IISc folder "ans_keys_final")


MANIFEST = [
    Entry(2026, "CS1", "keys/CS1_2026_key.pdf", "rows"),
    Entry(2026, "CS2", "keys/CS2_2026_key.pdf", "rows"),
    Entry(2025, "CS1", "keys/CS1_2025_key.pdf", "rows"),
    Entry(2025, "CS2", "keys/CS2_2025_key.pdf", "rows"),
    Entry(2024, "CS1", "keys/CS1_2024_final_key.pdf", "rows"),
    Entry(2024, "CS2", "keys/CS2_2024_final_key.pdf", "rows"),
    Entry(2023, "CS", "keys/CS_2023_key.pdf", "rows"),
    Entry(2022, "CS", "keys/CS_2022_key.pdf", "rows"),
    Entry(2020, "CS", "keys_archive/CS_2020_key_iitb.pdf", "rows"),
    Entry(2019, "CS", "keys_archive/CS_2019_key_iitd.pdf", "rows"),
    Entry(2018, "CS", "keys_archive/CS_2018_key_iitd.pdf", "rows"),
    Entry(2017, "CS1", "keys_archive/CS1_2017_key_iitd.pdf", "rows"),
    Entry(2017, "CS2", "keys_archive/CS2_2017_key_iitd.pdf", "rows"),
    Entry(2016, "CS1", "keys_archive/CS1_2016_final_key_iisc.pdf", "rows", finality="final"),
    Entry(2016, "CS2", "keys_archive/CS2_2016_final_key_iisc.pdf", "rows", finality="final"),
    Entry(2014, "CS1", "keys_archive/CS1_2014_key_iitkgp.pdf", "twocol"),
    Entry(2014, "CS2", "keys_archive/CS2_2014_key_iitkgp.pdf", "twocol"),
    Entry(2014, "CS3", "keys_archive/CS3_2014_key_iitkgp.pdf", "twocol"),
    *[Entry(2013, f"CS-{c}", "keys_archive/CS_2013_key_iitb.pdf", "ors", ors=c) for c in "ABCD"],
]

# ----------------------------------------------------------------------------- key cells
NUM = r"-?\d+(?:\.\d+)?"
NAT = re.compile(rf"^({NUM})\s+to\s+({NUM})$")


class KeyError_(ValueError):
    pass


def parse_one(q_type: str, raw: str) -> tuple[str, dict]:
    """One accepted answer: MCQ 'B', MSQ 'B;D' / 'B, C, D', NAT '2 to 2.5'."""
    if q_type == "MCQ" and re.fullmatch(r"[A-D]", raw):
        return "mcq", {"choice": raw}
    if q_type == "MSQ" and re.fullmatch(r"[A-D](\s*[;,]\s*[A-D])*", raw):
        return "msq", {"choices": sorted(set(re.split(r"\s*[;,]\s*", raw)))}
    if q_type == "NAT":
        m = NAT.match(raw)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            if lo > hi:
                raise KeyError_(f"NAT range reversed: {raw!r}")
            return "nat", {"min": lo, "max": hi}
    raise KeyError_(f"cannot read key {raw!r} for a {q_type} question")


def parse_key(q_type: str, raw: str) -> tuple[str, dict | None]:
    """Return (key_type, answer) for one key cell, or raise KeyError_.
    'MTA' = marks to all. 'X or Y' = either answer is accepted -> {"any_of": [X, Y]}.
    '11.0 : 11.0' (2016 NAT style) is read as '11.0 to 11.0'."""
    raw = " ".join(raw.split())
    if raw.upper() == "MTA":
        return "mta", None
    if q_type == "NAT":
        raw = re.sub(rf"^({NUM})\s*:\s*({NUM})$", r"\1 to \2", raw)
    parts = [p.strip() for p in re.split(r"\s+or\s+", raw, flags=re.I)]
    parsed = [parse_one(q_type, p) for p in parts]
    if len(parsed) == 1:
        return parsed[0]
    return parsed[0][0], {"any_of": [a for _, a in parsed]}


def infer_type(raw: str) -> str:
    """For layouts without a Type column (2013, 2014): the shape of the key says what it is."""
    raw = " ".join(raw.split())
    if re.fullmatch(r"[A-D]", raw):
        return "MCQ"
    if re.fullmatch(r"[A-D](\s*[;,]\s*[A-D])+", raw):
        return "MSQ"
    if NAT.match(re.sub(r"\s*:\s*", " to ", raw)):
        return "NAT"
    return "MCQ"  # parse_key will then refuse it with a clear message


# ----------------------------------------------------------------------------- layouts
ROW = re.compile(r"^\s*(\d{1,3})\s+(?:(\d+)\s+)?(MCQ|MSQ|NAT)\s+(GA|CS(?:-\d)?)\s+(.+?)\s+([12])\s*$")
TWO = re.compile(r"\b(GA|CS)\s+(\d{1,2})\s+(.+?)\s+([12])(?=\s{2,}(?:GA|CS)\s|\s*$)")
ORS_ROW = re.compile(r"^\s*(?:CS|GA)\s+(\d{1,2})\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")


def normalise(text: str) -> str:
    """PDF quirks: some keys use Unicode hyphens/minus signs for negative numbers, and the 2013 key
    spells marks-to-all out in words."""
    for ch in "\u2010\u2011\u2012\u2013\u2212":
        text = text.replace(ch, "-")
    return re.sub(r"Marks\s+to\s+All", "MTA", text, flags=re.I)


def pdf_text(path: Path) -> str:
    out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True).stdout
    return normalise(out)


def raw_rows(e: Entry, text: str) -> tuple[list[dict], list[str]]:
    """Layout-specific reading -> list of dicts (section, printed_number, q_type, marks, raw_key, exam_session)."""
    rows, problems = [], []
    if e.style == "rows":
        for line in text.splitlines():
            if not re.match(r"^\s*\d{1,3}\s", line):
                continue
            m = ROW.match(line)
            if not m:
                problems.append(f"unparsed row: {line.strip()!r}")
                continue
            n, sess, qt, sec, raw, marks = m.groups()
            rows.append(dict(printed_number=int(n), exam_session=int(sess or 1), q_type=qt, section=sec, marks=int(marks), raw_key=raw.strip()))
    elif e.style == "twocol":
        sess = re.search(r"SESSION\s*\W+\s*(\d+)", text)
        exam_session = int(sess.group(1)) if sess else 1
        for line in text.splitlines():
            for sec, n, raw, marks in TWO.findall(line):
                rows.append(dict(printed_number=int(n), exam_session=exam_session, q_type=infer_type(raw), section=sec,
                                 marks=int(marks), raw_key=raw.strip()))
        # sections print GA then CS, each starting at 1; order them GA first
        rows.sort(key=lambda r: (r["section"] != "GA", r["printed_number"]))
    elif e.style == "ors":
        col = "ABCD".index(e.ors)
        for line in text.splitlines():
            m = ORS_ROW.match(line)
            if not m:
                if re.match(r"^\s*(CS|GA)\s+\d", line):
                    problems.append(f"unparsed row: {line.strip()!r}")
                continue
            n = int(m.group(1))
            raw = m.group(2 + col)
            # The key lists no marks or sections. Standard GATE 2013 layout, checked by the 100-mark total below:
            # Q1-25 1 mark, Q26-55 2 marks (CS); Q56-60 1 mark, Q61-65 2 marks (GA).
            marks = 1 if n <= 25 or 56 <= n <= 60 else 2
            rows.append(dict(printed_number=n, exam_session=1, q_type=infer_type(raw), section="GA" if n >= 56 else "CS",
                             marks=marks, raw_key=raw))
    else:
        raise ValueError(e.style)
    return rows, problems


def parse_file(e: Entry, keys_dir: Path) -> dict:
    text = pdf_text(keys_dir / e.path)
    head = " ".join(text[:500].split()).lower()
    finality = e.finality or ("final" if "final answer key" in head else "unconfirmed")
    raw, problems = raw_rows(e, text)
    rows = []
    for r in raw:
        try:
            r["key_type"], r["answer"] = parse_key(r["q_type"], r["raw_key"])
        except KeyError_ as ex:
            problems.append(f"{r['section']} Q{r['printed_number']}: {ex}")
            continue
        rows.append(r)
    # overall slot number: the printed number when it already runs 1..65 once; otherwise file/section order
    # (2018-2020 restart numbering for the CS section, 2014 prints two tables).
    printed = [r["printed_number"] for r in rows]
    for i, r in enumerate(rows, 1):
        r["number"] = r["printed_number"] if sorted(printed) == list(range(1, len(rows) + 1)) else i
    return dict(rows=rows, problems=problems, finality=finality)


def validate(parsed: dict) -> list[str]:
    rows, errs = parsed["rows"], list(parsed["problems"])
    nums = [r["number"] for r in rows]
    if sorted(nums) != list(range(1, EXPECTED_QUESTIONS + 1)):
        missing = sorted(set(range(1, EXPECTED_QUESTIONS + 1)) - set(nums))
        dup = sorted({n for n in nums if nums.count(n) > 1})
        errs.append(f"question numbers are not exactly 1..{EXPECTED_QUESTIONS} (missing {missing}, duplicated {dup}, count {len(nums)})")
    total = sum(r["marks"] for r in rows)
    if total != EXPECTED_MARKS:
        errs.append(f"marks add up to {total}, expected {EXPECTED_MARKS}")
    ga = sum(1 for r in rows if r["section"] == "GA")
    if ga != EXPECTED_GA:
        errs.append(f"{ga} GA questions, expected {EXPECTED_GA}")
    keys = {(r["section"] == "GA", r["printed_number"]) for r in rows}
    if len(keys) != len(rows):
        errs.append("a (section, printed number) pair appears twice")
    return errs


# ----------------------------------------------------------------------------- SQL
def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def emit_sql(e: Entry, path: Path, parsed: dict) -> str:
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    sess = (f"(SELECT ps.id FROM paper_session ps JOIN paper p ON p.id = ps.paper_id "
            f"WHERE p.code = 'CS' AND ps.year = {e.year} AND ps.session_code = {q(e.sitting)})")
    fid = f"(SELECT id FROM source_file WHERE sha256 = {q(sha)})"
    out = [
        f"-- {e.year} {e.sitting}: {e.path} [{e.style}{' ' + e.ors if e.ors else ''}] ({len(parsed['rows'])} rows, finality={parsed['finality']})",
        f"INSERT INTO source_file (kind, storage_key, sha256, bytes, text_layer, note) VALUES "
        f"('answer_key', {q(e.path)}, {q(sha)}, {path.stat().st_size}, 'text', 'official key, imported by tools/import_keys.py') ON CONFLICT (sha256) DO NOTHING;",
        f"INSERT INTO paper_session_file (session_id, file_id, role) VALUES ({sess}, {fid}, 'answer_key') ON CONFLICT DO NOTHING;",
    ]
    values = []
    for r in parsed["rows"]:
        ans = q(json.dumps(r["answer"])) + "::jsonb" if r["answer"] is not None else "NULL"
        values.append(f"({sess}, {r['exam_session']}, {r['number']}, {r['printed_number']}, {q(r['q_type'])}, {q(r['section'])}, "
                      f"{r['marks']}, {q(r['key_type'])}, {ans}, {q(r['raw_key'])}, {fid})")
    out.append("INSERT INTO official_key_entry (session_id, exam_session, number, printed_number, q_type, section, marks, key_type, answer, raw_key, source_file_id) VALUES\n  "
               + ",\n  ".join(values) + ";")
    out.append(f"UPDATE paper_session SET key_provenance = 'official', key_finality = {q(parsed['finality'])}, "
               f"num_questions = {EXPECTED_QUESTIONS}, total_marks = {EXPECTED_MARKS} WHERE id = {sess};")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keys-dir", required=True, type=Path, help="folder that contains keys/ and keys_archive/")
    ap.add_argument("--dump-json", type=Path, help="also write the parsed rows, by '<year>_<sitting>', for tools/ingest_papers.py")
    args = ap.parse_args()

    sql, failed, dump = ["BEGIN;"], False, {}
    print(f"{'year':<6}{'sitting':<8}{'style':<8}{'rows':>5}{'marks':>7}{'MCQ':>5}{'MSQ':>5}{'NAT':>5}{'MTA':>5}  finality    result", file=sys.stderr)
    for e in MANIFEST:
        path = args.keys_dir / e.path
        parsed = parse_file(e, args.keys_dir)
        errs = validate(parsed)
        rows = parsed["rows"]
        cnt = lambda t: sum(1 for r in rows if r["q_type"] == t and r["key_type"] != "mta")
        print(f"{e.year:<6}{e.sitting:<8}{e.style:<8}{len(rows):>5}{sum(r['marks'] for r in rows):>7}{cnt('MCQ'):>5}{cnt('MSQ'):>5}{cnt('NAT'):>5}"
              f"{sum(1 for r in rows if r['key_type'] == 'mta'):>5}  {parsed['finality']:<11} {'OK' if not errs else 'REFUSED'}", file=sys.stderr)
        for err in errs[:12]:
            print(f"        - {err}", file=sys.stderr)
        if errs:
            failed = True
        else:
            sql.append(emit_sql(e, path, parsed))
            dump[f"{e.year}_{e.sitting}"] = rows
    if failed:
        print("\nNothing written: fix the refused files first.", file=sys.stderr)
        return 1
    sql.append("COMMIT;")
    if args.dump_json:
        args.dump_json.write_text(json.dumps(dump))
    print("\n".join(sql))
    return 0


if __name__ == "__main__":
    sys.exit(main())
