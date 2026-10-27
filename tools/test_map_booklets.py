"""Tests for tools/map_booklets.py:  python3 -I tools/test_map_booklets.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import map_booklets as mb

def q(stem, opts="A:first | B:second", m=1, t="MCQ"): return dict(stem=stem, opts=opts, m=m, type=t)
A = {1: q("Common data code segment executed on a processor"), 2: q("Common data code segment executed on a processor", opts="A:alpha | B:beta"),
     3: q("What is the capital of France?"), 4: q("Sort the array using quicksort pivot", m=2)}
# booklet B: same questions, different order, one with stray page-header text stuck on
B = {1: q("What is the capital of France? CS-B 3/20"), 2: q("Common data code segment executed on a processor", opts="A:alpha | B:beta"),
     3: q("Sort the array using quicksort pivot", m=2), 4: q("Common data code segment executed on a processor")}
m, problems = mb.match(A, B)
assert problems == [] and {x: a for x, (a, _) in m.items()} == {1: 3, 2: 2, 3: 4, 4: 1}, (m, problems)   # paired questions are told apart
# a pairing with different marks is refused
B2 = dict(B); B2[3] = q("Sort the array using quicksort pivot", m=1)
assert any("marks/type differ" in p for p in mb.match(A, B2)[1])
# a question with nothing in common is refused
B3 = dict(B); B3[1] = q("Entirely unrelated words zebra giraffe")
assert any("similarity" in p for p in mb.match(A, B3)[1])
print("map_booklets: all tests passed")
