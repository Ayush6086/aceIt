"""Tests for tools/ingest_papers.py (pure logic, no PDFs needed):  python3 -I tools/test_ingest_papers.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ingest_papers as ip

def row(page, y, x, text):
    return dict(page=page, y0=y, y1=y + 11, x0=x, words=[(x + i * 30, w) for i, w in enumerate(text.split())], text=text)

# running headers/footers are noise, by position and by wording (2023 puts its header at y=59)
assert ip.is_noise(row(1, 20, 72, "anything")) and ip.is_noise(row(1, 800, 72, "anything"))
assert ip.is_noise(row(8, 59, 72, "GATE 2023 Computer Science and Information Technology (CS)"))
assert ip.is_noise(row(8, 723, 72, "CS Page 1 of 83")) and ip.is_noise(row(1, 100, 72, "Organizing Institute: IISc Bengaluru"))
assert not ip.is_noise(row(1, 100, 78, "Q.1 If the sum"))
# section headers end a question and carry the marks
assert ip.is_section_header(row(1, 95, 99, "Q.6 – Q.10 Carry TWO marks each.")) and ip.is_section_header(row(1, 90, 72, "General Aptitude (GA)"))
assert ip.header_marks("Q.1 – Q.5 Carry ONE mark each.") == 1 and ip.header_marks("Q.46 – Q.555 Multiple Select Questions (MSQ), carry TWO marks each.") == 2

rows = [row(1, 90, 72, "General Aptitude (GA)"), row(1, 95, 99, "Q.1 – Q.5 Carry ONE mark each."),
        row(1, 130, 78, "Q.1 If the sum is"), row(1, 145, 120, "equal to"), row(1, 260, 78, "(A) starve"), row(1, 300, 78, "(B) reject"),
        row(1, 340, 78, "(C) feast"), row(1, 380, 78, "(D) deny"),
        row(2, 100, 78, "Q.2 Median of"), row(2, 114, 78, "(A) 13.5"), row(2, 150, 78, "(B) 14"), row(2, 190, 78, "(C) 11"), row(2, 230, 78, "(D) 18")]
qs, marks = ip.segment(rows)
assert sorted(qs) == [1, 2] and marks[1] == 1 and marks[2] == 1
q1 = ip.build(1, qs[1], {})
assert q1["stem"] == "If the sum is equal to" and [o["label"] for o in q1["options"]] == list("ABCD") and q1["options"][2]["text"] == "feast"
assert q1["flags"] == [] and q1["crops"][0]["page"] == 1
# the header line "Q.1 – Q.5" is NOT a question; a repeated number is not a new question
assert 1 in qs and len(qs[1]) == 6
# maths-style characters mean: show the original image
q = ip.build(9, [row(1, 100, 78, "Q.9 Let \U0001d43f be a language"), row(1, 120, 78, "(A) yes"), row(1, 140, 78, "(B) no"), row(1, 160, 78, "(C) a"), row(1, 180, 78, "(D) b")], {})
assert "math_symbols" in q["flags"]
# a question with an image inside its area is flagged
q = ip.build(3, qs[1], {1: [(100, 150, 300, 250)]}); assert "has_image" in q["flags"]
# cross-check with the key: wrong option count for the type, wrong count of questions, header marks that disagree
key = {n: dict(q_type="MCQ", marks=1, section="GA") for n in range(1, 66)}
good = [dict(number=n, options=[{}] * 4) for n in range(1, 66)]
assert ip.check_against_key(good, key, {}) == []
assert any("expected exactly" in e for e in ip.check_against_key(good[:60], key, {}))
bad = [dict(number=n, options=[{}] * (3 if n == 5 else 4)) for n in range(1, 66)]
assert any("Q5" in e and "3 options" in e for e in ip.check_against_key(bad, key, {}))
assert any("header says 2" in e for e in ip.check_against_key(good, key, {7: 2}))
nat_key = dict(key); nat_key[10] = dict(q_type="NAT", marks=1, section="CS")
assert any("NAT" in e for e in ip.check_against_key(good, nat_key, {}))
# the marker sits lower than its first text line: that line belongs to the NEW question, not the previous one
r1 = dict(page=1, y0=100, y1=111, x0=78, words=[(78, "Q.37"), (120, "Consider")], text="Q.37 Consider")
o1 = dict(page=1, y0=200, y1=211, x0=78, words=[(78, "(D)"), (120, "x")], text="(D) x")
first = dict(page=1, y0=458.4, y1=469.2, x0=120, words=[(120, "Which"), (150, "one")], text="Which one")
mark = dict(page=1, y0=465.3, y1=476.1, x0=77.7, words=[(77.7, "Q.38")], text="Q.38")
second = dict(page=1, y0=472.2, y1=483, x0=120, words=[(120, "IP"), (140, "addresses")], text="IP addresses")
qs2, _ = ip.segment([r1, o1, first, mark, second])
assert [r["text"] for r in qs2[38]] == ["Which one", "Q.38", "IP addresses"], qs2[38]
assert [r["text"] for r in qs2[37]] == ["Q.37 Consider", "(D) x"]
assert ip.build(38, qs2[38], {})["stem"] == "Which one IP addresses"  # marker row contributes no text
# papers with image labels: a wrong option count is flagged, not refused; a NAT with options is always refused
lax = [dict(number=n, options=[{}] * (2 if n == 5 else 4), flags=[]) for n in range(1, 66)]
assert ip.check_against_key(lax, key, {}, strict_options=False) == [] and "options_unreliable" in lax[4]["flags"]
nat_with_opts = [dict(number=n, options=[{}] * 4, flags=[]) for n in range(1, 66)]
assert any("NAT" in e for e in ip.check_against_key(nat_with_opts, nat_key, {}, strict_options=False))
# ---- older papers (2013-2018)
def mk(page, y, x0, text, sec="CS"):
    return dict(page=page, y0=y, y1=y + 11, x0=x0, words=[(x0 + i * 30, w) for i, w in enumerate(text.split())], text=text, sec=sec)

# inline options on one row: (A) .. (B) .. (C) .. (D) ..
q = ip.build(3, [dict(mk(1, 100, 78, "Q.3 What is it?"), is_marker=True), mk(1, 130, 78, "(A) meandering (B) timely (C) consistent (D) systematic")], {})
assert [o["text"] for o in q["options"]] == ["meandering", "timely", "consistent", "systematic"], q["options"]
# labels must come in order: a stray "(B)" inside the stem does not start an option
q = ip.build(3, [dict(mk(1, 100, 78, "Q.3 Choose (B) wisely"), is_marker=True), mk(1, 130, 78, "(A) x"), mk(1, 150, 78, "(B) y"), mk(1, 170, 78, "(C) z"), mk(1, 190, 78, "(D) w")], {})
assert q["stem"] == "Choose (B) wisely" and len(q["options"]) == 4
# numbering that restarts: GA Q.1 is slot 1, CS Q.1 is slot 11
rows = [mk(1, 100, 78, "Q.1 ga stem", "GA"), mk(1, 200, 78, "(A) a", "GA"), mk(2, 100, 78, "Q.1 cs stem", "CS"), mk(2, 200, 78, "(A) b", "CS")]
qs3, _ = ip.segment(rows, "restart"); assert sorted(qs3) == [1, 11]
qs3, _ = ip.segment(rows, "contiguous"); assert sorted(qs3) == [1]            # without 'restart' the second Q.1 is a repeat
# "Q.1 to Q.25 carry one mark each" (2013) is a header, not a question
assert ip.is_section_header(mk(1, 90, 77, "Q.1 to Q.25 carry one mark each.")) and ip.header_marks("Q.1 to Q.25 carry one mark each.") == 1
# a shared "Common Data" block belongs to BOTH questions it names
rows = [mk(1, 100, 77, "Common Data for Questions 48 and 49:"), mk(1, 114, 77, "The code segment is executed on a processor"),
        dict(mk(1, 200, 82, "Q.48 What is the minimum"), ), mk(1, 214, 114, "(A) 0 (B) 1 (C) 2 (D) 3"), mk(1, 260, 82, "Q.49 How many registers"), mk(1, 274, 114, "(A) 3 (B) 4 (C) 5 (D) 6")]
shared, _ = ip.segment(rows)
assert sorted(shared) == [48, 49] and any("Common Data" in r["text"] for r in shared[48]) and any("Common Data" in r["text"] for r in shared[49])
assert "shared_context" in ip.build(49, shared[49], {})["flags"]
# page selection: key pages are dropped; sets are cut at their cover pages
keypage = "GATE 2014\nAnswer Keys for CS\n" + "\n".join(f"{i} MCQ GA A 1" for i in range(1, 8))
assert ip.is_key_page(keypage) and not ip.is_key_page("Q.1 What is the capital of France?")
texts = ["", "SESSION - 1\n", "q a", "q b", keypage, "SESSION - 2\n", "q c", keypage]
e1, e2 = ip.Entry(2014, "CS1", "x", pages="session:1"), ip.Entry(2014, "CS2", "x", pages="session:2")
assert ip.select_pages(e1, texts) == {1, 2, 3} and ip.select_pages(e2, texts) == {5, 6}
texts = ["", "Question Booklet Code A\n", "a", "Question Booklet Code B\n", "b"]
assert ip.select_pages(ip.Entry(2013, "CS-A", "x", pages="booklet:A"), texts) == {1, 2} and ip.select_pages(ip.Entry(2013, "CS-B", "x", pages="booklet:B"), texts) == {3, 4}
texts = ["", "GATE 2016 General Aptitude - GA Set-5", "x", "GATE 2016 General Aptitude - GA Set-6", "y"]
assert ip.select_pages(ip.Entry(2016, "CS1", "x", pages="gaset:5"), texts) == {1, 2}
# OCR repair: garbled markers ("Qa4", "Oe", "Qs") that sit at the marker margin and fill the next number of the sequence are accepted
def ocr_row(page, y, x, text, sec="CS"):
    ws = text.split()
    return dict(page=page, y0=y, y1=y + 11, x0=x, words=[(x + 40 * i, w) for i, w in enumerate(ws)], text=text, sec=sec)
rows = [ocr_row(1, 100, 87, "Q.3 Which kinds of derivation is used by LR parsers"), ocr_row(1, 130, 119, "(A) Leftmost (B) Leftmost (C) Rightmost"),
        ocr_row(1, 160, 87, "Qa4 In 16-bit 2s complement the decimal number is"),         # digit kept: Q4
        ocr_row(1, 190, 87, "Q.5 Let U be a set of elements of size n"),
        ocr_row(1, 220, 87, "Oe If L is a regular language over which one is NOT regular"),   # no digit, the next number is 6
        ocr_row(1, 250, 87, "Qs Consider Z = X - Y where all are in sign magnitude form"),     # no digit, the next number is 7
        ocr_row(1, 280, 87, "Q9 Let X be a square matrix"),                                  # a wrong digit (9, expected 8): NOT repaired
        ocr_row(1, 310, 119, "On the other hand the answer is B and more words follow")]     # body text, off the margin: NOT a marker
assert ip.repair_ocr_markers(rows) == 3
assert [r["words"][0][1] for r in rows] == ["Q.3", "(A)", "Q.4", "Q.5", "Q.6", "Q.7", "Q9", "On"]
assert rows[4]["text"].startswith("Q.6 If L")
# an unrelated row at the margin that does not look like a marker is left alone, and a new GA/CS part restarts the sequence
rows = [ocr_row(1, 100, 87, "Q.9 ga stem words here", "GA"), ocr_row(1, 130, 87, "Hello this is a line", "GA"), ocr_row(2, 100, 87, "Q.1 cs stem words here", "CS"), ocr_row(2, 130, 87, "Qb a garbled second marker follows", "CS")]
assert ip.repair_ocr_markers(rows) == 1 and rows[3]["words"][0][1] == "Q.2" and rows[1]["words"][0][1] == "Hello"
# read_rows in OCR mode also accepts the marker without a dot and with letters for digits
assert ip.OCR_DIGITS and "Ql".lstrip("Q.").translate(ip.OCR_DIGITS) == "1" and "QI0".lstrip("Q.").translate(ip.OCR_DIGITS) == "10"
print("ingest_papers: all tests passed")
