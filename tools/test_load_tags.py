"""Tests for tools/load_tags.py:  python3 -I tools/test_load_tags.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import load_tags as lt

by_name, subject_of = lt.taxonomy_index()
# names resolve at every level; subjects work as "no specific topic" tags
assert lt.resolve("deadlock", by_name) == "operating-system/deadlock"
assert lt.resolve("dynamic-programming", by_name) == "algorithms/algorithm-design-techniques/dynamic-programming"
assert lt.resolve("algorithms", by_name) == "algorithms" and subject_of["algorithms"] == "algorithms"
assert subject_of[lt.resolve("verbal-ability", by_name)] == "general-aptitude"
for bad in ("not-a-topic", "Deadlock", ""):
    try:
        lt.resolve(bad, by_name); raise SystemExit(f"should have refused {bad!r}")
    except ValueError:
        pass
# every leaf and topic name in the taxonomy is unique as a last segment, so a tag can never be ambiguous
assert all(len(v) == 1 for v in by_name.values()), [k for k, v in by_name.items() if len(v) > 1]

t = lt.parse("# comment\n## 2024_CS1\n1 verbal-ability\n19 programming-in-c + recursion\n33 programming-in-c ?\n")
rows = t["2024_CS1"]
assert [r["number"] for r in rows] == [1, 19, 33]
assert rows[1]["second"] == "recursion" and rows[2]["low"] and not rows[0]["low"]
try:
    lt.parse("## x\nnot a tag line"); raise SystemExit("should have refused")
except ValueError:
    pass
# the two tag files together: every sitting once
import itertools
labels = [l for p in sorted((pathlib.Path(__file__).parent.parent / "data" / "tags").glob("gate_cs_*.txt")) for l in lt.parse(p.read_text())]
assert len(labels) == len(set(labels)) == 21, labels
print("load_tags: all tests passed")
