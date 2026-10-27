#!/usr/bin/env python3
"""Ingest GATE CS question papers that have a TEXT LAYER (2013-2014, 2016, 2018, 2022-2026) into the question bank.
(2015 and 2017 are scans without a text layer: they need OCR first.)

    python3 tools/ingest_papers.py --pyq-dir ~/Downloads/GATE/pyq --out-dir ~/Downloads/GATE/pyq/ingest > ingest.sql
    psql -d aceit -f ingest.sql        # after schema.sql, seed_paper_sessions.sql and the keys SQL

What it does, per paper
  1. Reads word positions with `pdftotext -bbox-layout` and finds each question ("Q.n" at the left margin).
  2. Cuts every question out of the page as a PNG (the original is always the visual source of truth, because
     stacked fractions, matrices and figures do not survive text extraction).
  3. Extracts the stem text and the (A)-(D) options.
  4. Cross-checks against the official key already in `official_key_entry`: question count, question type
     (MCQ/MSQ have 4 options, NAT has none), marks (from the "Carry ONE/TWO marks" headers).
  5. Emits SQL: question + question_version + the OFFICIAL question_key. Everything is inserted as status
     'draft'. A question becomes 'live' only through the publish gate (design §21.3), never here.

A paper that does not add up is REFUSED (no SQL for it). Per-question doubts are not refusals: they become
flags in question_version.extraction so the gate can hold the question back.

Needs poppler (pdftotext, pdftoppm). No other dependencies.
"""
import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PAGE_TOP, PAGE_BOTTOM = 44, 790          # text above/below is running header/footer (A4 = 842 pt); headers are also matched by wording
ROW_OVERLAP = 0.4                        # fraction of vertical overlap that makes two words one visual row
STEM_GAP = 8.0                           # rows closer than this (points) belong to the same stem
CROP_DPI = 144

@dataclass
class Entry:
    year: int
    sitting: str
    rel: str                      # paper file relative to --pyq-dir
    pages: str | None = None      # which pages of the file belong to this sitting (see select_pages)
    numbering: str = "contiguous" # 'restart' = GA is Q1-Q10 and the CS part restarts at Q1 (2014, 2016, 2018)
    text_ok: bool = True          # False = formulas are images and watermark letters pollute the text layer (2013, 2014)
    ocr: bool = False             # True = a scan made searchable by tools/ocr_pdf.py: OCR text only LOCATES the questions, students see the page image

    @property
    def label(self) -> str:
        return f"{self.year}_{self.sitting}"


MANIFEST = [
    Entry(2026, "CS1", "papers/CS1_2026.pdf"), Entry(2026, "CS2", "papers/CS2_2026.pdf"),
    Entry(2025, "CS1", "papers/CS1_2025.pdf"), Entry(2025, "CS2", "papers/CS2_2025.pdf"),
    Entry(2024, "CS1", "papers/CS1_2024.pdf"), Entry(2024, "CS2", "papers/CS2_2024.pdf"),
    Entry(2023, "CS", "papers/CS_2023.pdf"),
    Entry(2022, "CS", "papers/CS_2022.pdf"),
    Entry(2018, "CS", "archive/CS/2018_CS.pdf", numbering="restart"),
    Entry(2016, "CS1", "archive/CS/2016_CS.pdf", pages="gaset:5", numbering="restart"),
    Entry(2016, "CS2", "archive/CS/2016_CS.pdf", pages="gaset:6", numbering="restart"),
    Entry(2014, "CS1", "archive/CS/2014_CS.pdf", pages="session:1", numbering="restart", text_ok=False),
    Entry(2014, "CS2", "archive/CS/2014_CS.pdf", pages="session:2", numbering="restart", text_ok=False),
    Entry(2014, "CS3", "archive/CS/2014_CS.pdf", pages="session:3", numbering="restart", text_ok=False),
    Entry(2019, "CS", "ocr/2019_CS.pdf", numbering="restart", text_ok=False, ocr=True),
    Entry(2017, "CS1", "ocr/2017_CS1.pdf", numbering="qn", text_ok=False, ocr=True),
    Entry(2017, "CS2", "ocr/2017_CS2.pdf", numbering="qn", text_ok=False, ocr=True),
    *[Entry(2013, f"CS-{c}", "archive/CS/2013_CS.pdf", pages=f"booklet:{c}", text_ok=False) for c in "ABCD"],
]

WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', re.S)
PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S)
OCR_DIGITS = str.maketrans("lI|O", "1110")                  # letters OCR mistakes for digits
QSTART = re.compile(r"^Q\.(\d{1,2})$")
OPT = re.compile(r"^\(([A-D])\)$")
MATH_CHARS = re.compile("[\U0001D400-\U0001D7FF\u0300-\u036F\u2190-\u21FF\u2200-\u22FF\u0391-\u03A9\u03B1-\u03C9\u2211\u222B\u221A\u2264\u2265\u00D7\u00F7\u00B1\u2208\u2205]")
HEADER_WORDS = ("Computer Science and Information Technology Set", "Organizing Institute", "Page ")


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def page_texts(pdf: Path) -> list[str]:
    """Plain text of every page (1-based list, index 0 unused)."""
    return [""] + run(["pdftotext", "-layout", str(pdf), "-"]).split("\f")


def is_key_page(txt: str) -> bool:
    """Some papers have the official answer key printed after each set: not questions."""
    rows = re.findall(r"^\s*\d{1,2}\s+(?:MCQ|NAT|MSQ)\s+(?:GA|CS)", txt, re.M)
    return len(rows) >= 5 or bool(re.search(r"Answer Keys? for|Final Answer Key|Key\s*/\s*Range", txt[:600]))


def select_pages(e: Entry, texts: list[str]) -> set[int]:
    """Pages of the file that hold this sitting's questions (key pages are always dropped).
       None            every non-key page                                       (single-set papers)
       booklet:A       from the page printing 'Question Booklet Code A' to the next booklet   (2013)
       session:k       from the cover page 'SESSION - k' to the next session cover            (2014)
       gaset:N         from the page headed 'GA Set-N' to the first page of a different GA set (2016)"""
    n = len(texts) - 1
    first = lambda p: next((l.strip() for l in texts[p].splitlines() if l.strip()), "")
    if e.pages is None:
        pages = range(1, n + 1)
    else:
        kind, val = e.pages.split(":")
        if kind == "booklet":
            starts = {m.group(1): p for p in range(1, n + 1) for m in [re.search(r"Question Booklet Code\s+([A-D])\b", texts[p])] if m}
            order = sorted(starts.values())
            s = starts[val]
            end = next((x - 1 for x in order if x > s), n)
        elif kind == "session":
            cover = {int(m.group(1)): p for p in range(1, n + 1) for m in [re.fullmatch(r"SESSION - (\d+)", first(p))] if m}
            s = cover[int(val)]
            end = cover.get(int(val) + 1, n + 1) - 1
        elif kind == "gaset":
            hdr = {p: int(m.group(1)) for p in range(1, n + 1) for m in [re.search(r"GA Set-(\d+)", texts[p][:300])] if m}
            s = min(p for p, v in hdr.items() if v == int(val))
            end = next((p - 1 for p in sorted(hdr) if p > s and hdr[p] != int(val)), n)
        else:
            raise ValueError(e.pages)
        pages = range(s, end + 1)
    return {p for p in pages if not is_key_page(texts[p])}


def page_sections(texts: list[str]) -> dict[int, str]:
    """GA or CS for every page, from the page header (the header row itself is dropped as noise later)."""
    out, cur = {}, "GA"
    for p in range(1, len(texts)):
        head = texts[p][:400]
        if re.search(r"General Aptitude", head):
            cur = "GA"
        elif re.search(r"COMPUTER|Computer Science", head) and not re.search(r"Question Booklet|SESSION|Instructions", head):
            cur = "CS"
        out[p] = cur
    return out


def read_rows(pdf: Path, drop_tall: float = 0, ocr: bool = False) -> list[dict]:
    """Visual rows of every page: dict(page, y0, y1, x0, words=[(x0, text)...], text)."""
    xml = run(["pdftotext", "-bbox-layout", str(pdf), "-"])
    rows = []
    for pno, (_, _, body) in enumerate(PAGE.findall(xml), 1):
        words = [(float(a), float(b), float(c), float(d), html.unescape(t).strip()) for a, b, c, d, t in WORD.findall(body)]
        # a big diagonal watermark ("GATE 2014") is in the text layer as tall fragments; drop them when asked
        words = sorted((w for w in words if w[4] and not (drop_tall and w[3] - w[1] > drop_tall)), key=lambda w: (w[1], w[0]))
        # One visual row = words whose vertical extents overlap by at least 40% of the smaller one.
        # (Grouping by top edge alone put the first line of a question under the PREVIOUS question when the
        # "Q.38" marker sat a few points lower than its own text.)
        groups, cur, lo, hi = [], [], 0.0, 0.0
        for w in words:
            h = min(w[3] - w[1], hi - lo) if cur else 0
            overlap = min(w[3], hi) - max(w[1], lo) if cur else 0
            if cur and overlap < ROW_OVERLAP * max(h, 1.0):
                groups.append(cur)
                cur = []
            if not cur:
                lo, hi = w[1], w[3]
            else:
                lo, hi = min(lo, w[1]), max(hi, w[3])
            cur.append(w)
        if cur:
            groups.append(cur)
        for g in groups:
            g.sort(key=lambda w: w[0])
            merged = []
            for w in g:                              # some papers print "Q. 4" with a space
                if merged and merged[-1][4] == "Q." and re.fullmatch(r"\d{1,3}", w[4]):
                    p = merged.pop()
                    w = (p[0], p[1], w[2], max(p[3], w[3]), "Q." + w[4])
                merged.append(w)
            g = merged
            if ocr and g and re.fullmatch(r"Q\.?[0-9lIO|]{1,2}", g[0][4]):      # OCR writes the marker "Q.1" as "Q1", "Ql" or "QI"
                g[0] = (g[0][0], g[0][1], g[0][2], g[0][3], "Q." + g[0][4].lstrip("Q.").translate(OCR_DIGITS))
            rows.append(dict(page=pno, y0=min(w[1] for w in g), y1=max(w[3] for w in g), x0=g[0][0],
                             words=[(w[0], w[4]) for w in g], text=" ".join(w[4] for w in g)))
    return rows


def repair_ocr_markers(rows: list[dict]) -> int:
    """OCR garbles some question markers beyond reading ("Qa4" for Q.4, "Oe" for Q.7, "Qs" for Q.8). A line that starts at the marker
    margin, looks like a marker and fills the NEXT number of the sequence (within the same GA/CS part) is accepted as that marker.
    Rows need their 'sec'. Returns how many were repaired; the strict checks against the official key still judge the result."""
    margin = {}
    for r in rows:                                             # where the markers sit on each page
        if QSTART.match(r["words"][0][1]):
            margin.setdefault(r["page"], []).append(r["x0"])
    fixed, last, sec = 0, 0, None
    for r in rows:
        if is_noise(r) or is_section_header(r) or CTX.match(r["text"]):
            continue
        if r["sec"] != sec:
            sec, last = r["sec"], 0
        first = r["words"][0][1]
        m = QSTART.match(first)
        if m:
            last = int(m.group(1)); continue
        xs = margin.get(r["page"])
        if xs and abs(r["x0"] - sorted(xs)[len(xs) // 2]) <= 10 and len(r["words"]) > 2 and re.fullmatch(r"[QO0][A-Za-z0-9|]{0,2}", first):
            digits = re.sub(r"\D", "", first[1:].translate(OCR_DIGITS))               # the first letter is the "Q" (or a misread "Q"), never a digit
            if not digits or int(digits) == last + 1:
                r["words"][0] = (r["words"][0][0], f"Q.{last + 1}")
                r["text"] = f"Q.{last + 1} " + " ".join(w[1] for w in r["words"][1:])
                last += 1; fixed += 1
    return fixed


def is_noise(r: dict) -> bool:
    """Running headers and footers: by position AND by wording (2023 puts its header at y=59)."""
    t = r["text"]
    if r["y0"] < PAGE_TOP or r["y0"] > PAGE_BOTTOM:
        return True
    if re.search(r"\bPage \d+ of \d+\b", t) or t.startswith("Organizing Institute"):
        return True
    if r["y0"] < 90 and re.match(r"^(GATE \d{4} )?Computer Science and Information Technology( Set| \(CS\d?\)|$)", t):
        return True
    if r["y0"] < 90 and re.match(r"^(GATE \d{4}\b|20\d\d\s+COMPUTER)", t):       # 2013-2018 running headers
        return True
    return False


def is_section_header(r: dict) -> bool:
    t = r["text"]
    return bool(re.match(r"^(General Aptitude|Computer Science and Information Technology \()", t)
                or re.match(r"^Q\.\d+\s*(?:[–—-]|to)\s*Q\.\d+", t))      # "Q.6 - Q.10" and 2013's "Q.1 to Q.25"


def header_marks(t: str) -> int | None:
    if re.search(r"Carry\s+ONE\s+mark", t, re.I):
        return 1
    if re.search(r"Carry\s+TWO\s+mark", t, re.I):
        return 2
    return None


def read_images(pdf: Path) -> dict[int, list[tuple]]:
    """page -> [(x0, y0, x1, y1) in points] of embedded images, via pdftohtml -xml (images are written to a temp dir and discarded).
    Images in the running header (the logo) are ignored."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["pdftohtml", "-xml", "-q", str(pdf), str(Path(d) / "o")], capture_output=True, check=True)
        xml = (Path(d) / "o.xml").read_text(errors="ignore")
    out = {}
    for m in re.finditer(r'<page number="(\d+)"[^>]*height="(\d+)"[^>]*width="(\d+)">(.*?)</page>', xml, re.S):
        pno, h = int(m.group(1)), float(m.group(2))
        k = 841.92 / h                                   # xml units -> points
        for im in re.finditer(r'<image top="(-?\d+)" left="(-?\d+)" width="(\d+)" height="(\d+)"', m.group(4)):
            top, left, w, hh = (float(x) * k for x in im.groups())
            if top < PAGE_TOP or w < 15 or hh < 15:
                continue
            out.setdefault(pno, []).append((left, top, left + w, top + hh))
    # a page watermark/logo repeats at the same place and size on many pages: it is not a figure
    sig = lambda b: (round(b[0]), round(b[1]), round(b[2] - b[0]), round(b[3] - b[1]))
    seen = {}
    for boxes in out.values():
        for b in set(map(sig, boxes)):
            seen[b] = seen.get(b, 0) + 1
    return {p: [b for b in boxes if seen[sig(b)] < 3] for p, boxes in out.items()}


def pull_stem_above(cand: list[dict], marker: dict) -> list[dict]:
    """Stem lines printed ABOVE their question marker (some papers centre the marker on the stem).
    Walk back from the marker over rows that touch each other (gap < STEM_GAP) and are not an option line."""
    moved, next_y = [], marker["y0"]
    while cand:
        p = cand[-1]
        if p["page"] != marker["page"] or next_y - p["y1"] > STEM_GAP or re.match(r"^\([A-D]\)$", p["words"][0][1]):
            break
        moved.insert(0, cand.pop())
        next_y = p["y0"]
    return moved


CTX = re.compile(r"^(Common Data for Questions|Statement for Linked Answer Questions)\s+(\d+)\s*(?:and|&|,|to|-)\s*(\d+)", re.I)


QN = re.compile(r"^Quest\w*\s+Num\w*\s*[:;.]?\s*(\d{1,3})\b(?:.*?Corr\w*\s*[:;.]?\s*(\d))?")
QNO = re.compile(r"^Q\.?\s*No\.?\s*(\d{1,2})\b")
RANGE_HDR = re.compile(r"^Q\.?\s?\d+\s*[-\u2013\u2014]\s*Q\.?\s?\d+\b.*carry", re.I)


def segment_marked(rows: list[dict], kind: str) -> tuple[dict, dict]:
    """Layouts whose question markers are not 'Q.n'.
       qn   the exam-portal layout (2017): 'Question Number : N   Correct : 1   Wrong : -0.33'. N is the number in the official key (subject
            part first, aptitude last), 'Correct' is the marks, and the marker row holds nothing else, so its text is dropped from the stem.
       qno  2020: 'Q.No. 6  <first line of the stem>' with section headers 'Q6 - Q10 carry two marks each' (no dots); the marker words are
            merged into 'Q.6' and the rest of the row stays in the stem."""
    questions, marks, cur, cur_marks, cs, prev_raw, guessed, order = {}, {}, None, None, False, 0, set(), []
    for r in rows:
        if r["y0"] > PAGE_BOTTOM or re.search(r"\bPage \d+ of \d+\b", r["text"]):      # no running header here: questions may start at the very top of a page
            continue
        if kind == "qno" and RANGE_HDR.match(r["text"]):
            cur, cur_marks = None, header_marks(r["text"]) or cur_marks
            continue
        m = (QN if kind == "qn" else QNO).match(r["text"])
        if kind == "qno" and not m and r["x0"] < 130 and prev_raw and re.fullmatch(r"Q\.?\s*No\.?", r["words"][0][1]) and not (len(r["words"]) > 1 and r["words"][1][1].isdigit()):
            m = re.match(r"(\d+)", str(prev_raw + 1))                              # "Q.No." whose number OCR lost: it is the next one in the sequence
            guessed.add(prev_raw + 1 + (10 if cs else 0))
            r["words"] = [(r["words"][0][0], "Q.No."), (r["words"][0][0] + 1, str(prev_raw + 1))] + r["words"][1:]
            r["text"] = " ".join(w[1] for w in r["words"])
        if m and r["x0"] < 130:
            raw = int(m.group(1))
            if kind == "qno" and raw < prev_raw and raw <= 3:
                cs = True                                                      # the numbering dropped back to 1: the subject part has begun
            prev_raw = raw
            n = raw + (10 if kind == "qno" and cs else 0)                         # qno restarts the numbering for the subject part
            if n in questions:
                cur = None; continue
            if kind == "qn":
                r["words"], r["text"], r["wide"] = [(r["words"][0][0], f"Q.{n}")], f"Q.{n}", True
                mk = int(m.group(2)) if m.group(2) else None
            else:
                k = 2 if len(r["words"]) > 1 and re.fullmatch(r"\d{1,2}", r["words"][1][1]) else 1      # "Q.No." "6"  or  "Q.No.6"
                r["words"] = [(r["words"][0][0], f"Q.{int(m.group(1))}")] + r["words"][k:]
                r["text"] = " ".join(w[1] for w in r["words"])
                mk = cur_marks
            r["is_marker"] = True
            cur = n
            questions[cur], marks[cur] = [r], mk
            order.append(cur)
        elif cur is not None:
            questions[cur].append(r)
    # A run of guessed numbers is only believed if it exactly fills the gap between the explicit numbers around it. If a marker was lost
    # entirely the guesses would shift every later number by one and attach the wrong answer key, so they are dropped and the paper is refused.
    i = 0
    while i < len(order):
        if order[i] in guessed:
            j = i
            while j < len(order) and order[j] in guessed:
                j += 1
            before = order[i - 1] if i else 0
            after = order[j] if j < len(order) else None
            if after is not None and after - before - 1 != j - i:
                for n in order[i:j]:
                    questions.pop(n, None); marks.pop(n, None)
            i = j
        else:
            i += 1
    return questions, marks


def segment(rows: list[dict], numbering: str = "contiguous") -> tuple[dict, dict]:
    """-> ({slot: [rows]}, {slot: marks_from_header}). Rows are in reading order.
    slot = the question's place 1..65 in the sitting. With numbering='restart' the CS part starts again at Q.1,
    so its slot is the printed number + 10 (GA is slots 1-10). A 'Common Data / Linked Answer' block is shared
    by the questions it names, so its rows are copied into each of them."""
    if numbering in ("qn", "qno"):
        return segment_marked(rows, numbering)
    questions, marks, contexts = {}, {}, {}
    cur, cur_marks, orphans, ctx_range = None, None, [], None
    for r in rows:
        if is_noise(r):
            continue
        mctx = CTX.match(r["text"])
        if mctx:                                   # shared statement for the next two questions
            cur, orphans, ctx_range = None, [r], (int(mctx.group(2)), int(mctx.group(3)))
            continue
        if is_section_header(r):
            cur, orphans, ctx_range = None, [], None
            m = header_marks(r["text"])
            if m:
                cur_marks = m
            continue
        first = r["words"][0][1]
        m = QSTART.match(first)
        if m and r["x0"] < 130 and not (len(r["words"]) > 1 and r["words"][1][1] in ("\u2013", "-", "\u2014", "to")):
            offset = 10 if numbering == "restart" and r.get("sec") == "CS" else 0
            n = int(m.group(1)) + offset
            if n in questions:
                cur = None            # a repeated number is not a new question
                continue
            if cur is not None:       # stem lines above the marker were filed under the previous question
                prev = questions[cur]
                moved = pull_stem_above(prev[1:], r)
                del prev[len(prev) - len(moved):]
            else:                     # ... or right after a section header / shared statement
                moved = pull_stem_above(orphans, r)
            if ctx_range:
                for k in range(ctx_range[0], ctx_range[1] + 1):
                    contexts[k + offset] = [dict(o, shared=True) for o in orphans]
                ctx_range = None
            r["is_marker"] = True
            cur = n
            questions[cur] = contexts.get(n, []) + moved + [r]
            marks[cur] = cur_marks
            orphans = []
        elif cur is not None:
            questions[cur].append(r)
        else:
            orphans.append(r)
    for n, rs in questions.items():           # the same shared rows must not appear twice in one question
        seen, out = set(), []
        for r in rs:
            if id(r) not in seen:
                seen.add(id(r)); out.append(r)
        questions[n] = out
    return questions, marks


def build(number: int, rows: list[dict], images: dict) -> dict:
    """Stem, options, crops and flags of one question."""
    stem_rows, opts, cur_opt, nxt = [], {}, None, 0
    printed = None
    for r in rows:
        words = r["words"][:]
        if r.get("is_marker") and words and QSTART.match(words[0][1]):
            printed = int(QSTART.match(words[0][1]).group(1))
            words = words[1:]                     # drop the "Q.n" marker (it may sit between the stem lines)
        buf = []

        def flush():
            text = " ".join(buf).strip()
            if buf:
                (opts[cur_opt] if cur_opt else stem_rows).append((r, text))
            buf.clear()

        for w in words:
            m = OPT.match(w[1])
            if m and nxt < 4 and m.group(1) == "ABCD"[nxt]:    # labels must come in order A, B, C, D (also inline: "(A) x (B) y")
                flush()
                cur_opt = m.group(1)
                opts[cur_opt] = []
                nxt += 1
                opts[cur_opt].append((r, ""))                  # an option with no text still exists
                continue
            buf.append(w[1])
        flush()
    stem = " ".join(t for _, t in stem_rows if t)
    options = [{"label": k, "text": " ".join(t for _, t in v if t).strip()} for k, v in sorted(opts.items())]

    flags = []
    pages = sorted({r["page"] for r in rows})
    # short, centred fragments are the pieces of a stacked fraction / matrix / exponent
    for r, t in stem_rows + [x for v in opts.values() for x in v]:
        if r["x0"] > 150 and 0 < len(t) <= 6 and not t.endswith((".", ":")):
            flags.append("stacked_math")
            break
    # Math in a text layer is unreliable: subscripts, overlines and fractions lose their structure
    # (e.g. L1, L2, L3 came out as "L , L ... 1 2 3"). Any maths-style character means: show the original image.
    alltext = stem + " ".join(o["text"] for o in options)
    if MATH_CHARS.search(alltext):
        flags.append("math_symbols")
    if not stem or stem[0].islower():
        flags.append("stem_start_unclear")        # a real stem rarely starts mid-sentence: a boundary may be wrong
    if any(not o["text"] for o in options):
        flags.append("option_without_text")      # option is an image or got lost
    # crops: one band per page the question touches
    crops = []
    for p in pages:
        pr = [r for r in rows if r["page"] == p]
        wide = any(r.get("wide") for r in rows)               # the exam-portal layout (2017) runs to the page edges; the others keep their margins
        top = round(max(0 if wide else PAGE_TOP, min(r["y0"] for r in pr) - 6), 1)
        crops.append(dict(page=p, bbox=[2 if wide else 40, top, 600 if wide else 555, round(min(PAGE_BOTTOM + 40 if wide else PAGE_BOTTOM, max(r["y1"] for r in pr) + 6), 1)]))
    if len(pages) > 1:
        flags.append("spans_pages")
    for c in crops:                                   # a real embedded image inside the question's area
        if any(im[1] < c["bbox"][3] and im[3] > c["bbox"][1] for im in images.get(c["page"], [])):
            flags.append("has_image")
            break
    if any(r.get("shared") for r in rows):
        flags.append("shared_context")
    return dict(number=number, printed=printed, stem=stem, options=options, crops=crops, flags=sorted(set(flags)))


def crop_png(pdf: Path, crop: dict, dest: Path) -> None:
    s = CROP_DPI / 72
    x0, y0, x1, y1 = crop["bbox"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftoppm", "-png", "-r", str(CROP_DPI), "-f", str(crop["page"]), "-l", str(crop["page"]),
                    "-x", str(int(x0 * s)), "-y", str(int(y0 * s)), "-W", str(int((x1 - x0) * s)), "-H", str(int((y1 - y0) * s)),
                    "-singlefile", str(pdf), str(dest.with_suffix(""))], check=True, capture_output=True)


def check_against_key(qs: list[dict], key: dict[int, dict], header_marks_: dict, strict_options: bool = True) -> list[str]:
    """Refusals: things that mean the paper was read wrongly. Per-question doubts are flags, not refusals."""
    errs = []
    nums = sorted(q["number"] for q in qs)
    if nums != list(range(1, 66)):
        errs.append(f"found questions {nums[:3]}..{nums[-3:]} ({len(nums)}), expected exactly 1..65 once each")
    for q in qs:
        k = key.get(q["number"])
        if not k:
            errs.append(f"Q{q['number']}: no key row")
            continue
        n_opt = len(q["options"])
        if k["q_type"] in ("MCQ", "MSQ") and n_opt != 4:
            if strict_options:
                errs.append(f"Q{q['number']}: {k['q_type']} question has {n_opt} options (expected 4)")
            else:                       # papers whose option labels are images: the crop is the truth, not the text
                q["flags"] = sorted(set(q["flags"]) | {"options_unreliable"})
        if k["q_type"] == "NAT" and n_opt != 0:
            errs.append(f"Q{q['number']}: NAT question has {n_opt} options (expected none)")
        hm = header_marks_.get(q["number"])
        if hm and hm != k["marks"]:
            errs.append(f"Q{q['number']}: paper header says {hm} mark(s), key says {k['marks']}")
    return errs


def q_(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def emit_sql(year, sitting, rel, pdf: Path, qs: list[dict], out_rel: str) -> str:
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    sess = (f"(SELECT ps.id FROM paper_session ps JOIN paper p ON p.id = ps.paper_id "
            f"WHERE p.code = 'CS' AND ps.year = {year} AND ps.session_code = {q_(sitting)})")
    fid = f"(SELECT id FROM source_file WHERE sha256 = {q_(sha)})"
    out = [f"-- {year} {sitting}: {rel} ({len(qs)} questions)",
           f"INSERT INTO source_file (kind, storage_key, sha256, bytes, text_layer, note) VALUES "
           f"('question_paper', {q_(rel)}, {q_(sha)}, {pdf.stat().st_size}, 'text', 'official paper, ingested by tools/ingest_papers.py') ON CONFLICT (sha256) DO NOTHING;",
           f"INSERT INTO paper_session_file (session_id, file_id, role) VALUES ({sess}, {fid}, 'question_paper') ON CONFLICT DO NOTHING;"]
    for q in qs:
        n, k = q["number"], q["key"]
        figures = [dict(kind="page_crop", path=f"{out_rel}/{c['file']}", page=c["page"], bbox=c["bbox"]) for c in q["crops"]]
        extraction = dict(reader="pdf-text-layer", printed=q.get("printed"), flags=q["flags"], crops=len(q["crops"]), second_reader=None,
                          display="text" if not q["flags"] else "image")   # image = show the original crop, not the extracted text
        opts = json.dumps(q["options"]) if q["options"] else None
        qid = f"(SELECT q.id FROM question q WHERE q.session_id = {sess} AND q.number = {n} AND q.origin = 'official_pyq')"
        vid = f"(SELECT current_version_id FROM question WHERE id = {qid})"
        out.append(
            f"INSERT INTO question (session_id, number, section, q_type, marks, origin, status) VALUES "
            f"({sess}, {n}, {q_(k['section'] if k['section'] == 'GA' else 'CS')}, {q_(k['q_type'])}, {k['marks']}, 'official_pyq', 'draft');")
        out.append(
            f"INSERT INTO question_version (question_id, version, stem_md, options, figures, extraction, created_by) VALUES "
            f"({qid}, 1, {q_(q['stem'])}, {q_(opts) + '::jsonb' if opts else 'NULL'}, {q_(json.dumps(figures))}::jsonb, "
            f"{q_(json.dumps(extraction))}::jsonb, 'ingest_papers.py');")
        out.append(f"UPDATE question SET current_version_id = (SELECT id FROM question_version WHERE question_id = {qid} AND version = 1) WHERE id = {qid};")
        # attach the official key (staged earlier by import_keys.py) to this version
        out.append(
            f"INSERT INTO question_key (question_version_id, key_type, answer, status, finality, source_file_id, source_ref) "
            f"SELECT {vid}, e.key_type, e.answer, "
            f"CASE e.key_type WHEN 'mta' THEN 'OFFICIAL_MTA' WHEN 'dropped' THEN 'OFFICIAL_DROPPED' ELSE 'OFFICIAL' END, "
            f"ps.key_finality, e.source_file_id, 'raw=' || e.raw_key "
            f"FROM official_key_entry e JOIN paper_session ps ON ps.id = e.session_id "
            f"WHERE e.session_id = {sess} AND e.number = {n};")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pyq-dir", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path, help="where the question PNG crops are written")
    ap.add_argument("--key-json", required=True, type=Path, help="output of tools/import_keys.py --dump-json (key rows by sitting)")
    args = ap.parse_args()
    keys = json.loads(args.key_json.read_text())

    sql, failed = ["BEGIN;"], False
    print(f"{'year':<6}{'sitting':<8}{'qs':>4}{'clean':>7}{'image':>8}{'math':>6}{'sym':>5}{'opt?':>6}{'span':>6}{'ctx':>5}  result", file=sys.stderr)
    cache = {}                                              # one read per PDF (several sittings can share a file)
    for e in MANIFEST:
        pdf = args.pyq_dir / e.rel
        if e.rel not in cache:
            texts = page_texts(pdf)
            cache[e.rel] = (texts, page_sections(texts), read_rows(pdf, 0 if (e.text_ok or e.ocr) else 16, ocr=e.ocr), read_images(pdf) if e.text_ok else {})
        texts, secs, all_rows, images = cache[e.rel]
        pages = select_pages(e, texts)
        rows = [dict(r, sec=secs[r["page"]]) for r in all_rows if r["page"] in pages]
        if e.ocr and e.numbering not in ("qn", "qno"):
            repair_ocr_markers(rows)
        raw, hm = segment(rows, e.numbering)
        qs = [build(n, r, images) for n, r in sorted(raw.items())]
        for q in qs:
            if not e.text_ok:
                q["flags"] = sorted(set(q["flags"]) | {"text_layer_unreliable"})
        key = {r["number"]: r for r in keys[e.label]}
        errs = check_against_key(qs, key, hm, strict_options=e.text_ok)
        cnt = lambda f: sum(1 for q in qs if f in q["flags"])
        print(f"{e.year:<6}{e.sitting:<8}{len(qs):>4}{sum(1 for q in qs if not q['flags']):>7}{cnt('has_image'):>8}{cnt('stacked_math'):>6}{cnt('math_symbols'):>5}"
              f"{cnt('option_without_text'):>6}{cnt('spans_pages'):>6}{cnt('shared_context'):>5}  {'OK' if not errs else 'REFUSED'}", file=sys.stderr)
        for err in errs[:10]:
            print(f"        - {err}", file=sys.stderr)
        if errs:
            failed = True
            continue
        for q in qs:
            q["key"] = key[q["number"]]
            for i, c in enumerate(q["crops"], 1):
                c["file"] = f"{e.label}/Q{q['number']:02d}_{i}.png"
                crop_png(pdf, c, args.out_dir / c["file"])
        sql.append(emit_sql(e.year, e.sitting, e.rel, pdf, qs, args.out_dir.name))
    if failed:
        print("\nNothing written for the refused papers. Fix them first.", file=sys.stderr)
        return 1
    sql.append("COMMIT;")
    print("\n".join(sql))
    return 0


if __name__ == "__main__":
    sys.exit(main())
