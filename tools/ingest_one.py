#!/usr/bin/env python3
"""Try ingest_papers.py on ONE sitting (typically an OCR'd scan) and print its report; writes SQL and crops only with --write.

    python3 tools/ingest_one.py --key-json build/dev/keys.json --year 2019 --sitting CS --rel ocr/2019_CS.pdf [--numbering restart] [--pages booklet:A] [--write ...]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ingest_papers as ip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pyq-dir", type=Path, default=Path.home() / "Downloads" / "GATE" / "pyq")
    ap.add_argument("--out-dir", type=Path, default=Path.home() / "Downloads" / "GATE" / "pyq" / "ingest")
    ap.add_argument("--key-json", required=True, type=Path)
    ap.add_argument("--year", type=int, required=True); ap.add_argument("--sitting", required=True); ap.add_argument("--rel", required=True)
    ap.add_argument("--pages"); ap.add_argument("--numbering", default="contiguous")
    ap.add_argument("--write", action="store_true", help="also cut the crops and print the SQL")
    ap.add_argument("--show", type=int, default=0, help="print the first N questions as read")
    a = ap.parse_args()
    keys = json.loads(a.key_json.read_text())
    e = ip.Entry(a.year, a.sitting, a.rel, a.pages, a.numbering, text_ok=False)        # OCR text is a locator only: show the page image
    pdf = a.pyq_dir / e.rel
    texts = ip.page_texts(pdf)
    rows = ip.read_rows(pdf, 0, ocr=True)                               # no watermark filter: OCR boxes of real markers can be tall
    secs = ip.page_sections(texts)
    pages = ip.select_pages(e, texts)
    rows = [dict(r, sec=secs[r["page"]]) for r in rows if r["page"] in pages]
    repaired = ip.repair_ocr_markers(rows) if a.numbering not in ("qn", "qno") else 0
    raw, hm = ip.segment(rows, e.numbering)
    qs = [ip.build(n, r, {}) for n, r in sorted(raw.items())]
    for q in qs:
        q["flags"] = sorted(set(q["flags"]) | {"text_layer_unreliable"})
    key = {r["number"]: r for r in keys[e.label]}
    errs = ip.check_against_key(qs, key, hm, strict_options=False)
    print(f"{e.label}: {repaired} garbled markers repaired, {len(pages)} pages, {len(rows)} rows, {len(qs)} questions found, key rows {len(key)}", file=sys.stderr)
    print("numbers found:", sorted(raw)[:80], file=sys.stderr)
    for q in qs[:a.show]:
        print(f"  Q{q['number']} [{q.get('marks')}] {q['stem'][:90]!r} opts={len(q.get('options') or [])}", file=sys.stderr)
    for err in errs[:25]:
        print("  -", err, file=sys.stderr)
    print("RESULT:", "OK" if not errs else f"REFUSED ({len(errs)} problems)", file=sys.stderr)
    if errs or not a.write:
        return 1 if errs else 0
    for q in qs:
        q["key"] = key[q["number"]]
        for i, c in enumerate(q["crops"], 1):
            c["file"] = f"{e.label}/Q{q['number']:02d}_{i}.png"
            ip.crop_png(pdf, c, a.out_dir / c["file"])
    print("BEGIN;\n" + ip.emit_sql(e.year, e.sitting, e.rel, pdf, qs, a.out_dir.name) + "\nCOMMIT;")
    return 0


if __name__ == "__main__":
    sys.exit(main())
