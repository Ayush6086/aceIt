"""Tests for tools/load_taxonomy.py:  python3 -I tools/test_load_taxonomy.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from load_taxonomy import norm, slugify, check

assert norm("divide‐and‐conquer") == "divide and conquer" and norm("B and B+ trees") == "b and b+ trees"
assert slugify("Design of arithmetic and logic unit (ALU)") == "design-of-arithmetic-and-logic-unit-alu"

SYL = "Section 1: Algebra Matrices, determinants. Calculus: Limits and integration."
def tax(topics, subj="Algebra"):
    return {"subjects": [{"name": subj, "topics": topics}]}

ok = tax([{"name": "Matrices", "aliases": ["matrix"]}, {"name": "determinants"}, {"name": "Calculus"},
          {"name": "Limits", "aliases": ["lim"]}, {"name": "integration"}])
assert check(ok, SYL) == [], check(ok, SYL)
# an invented topic name must be refused unless it is marked derived
bad = tax(ok["subjects"][0]["topics"] + [{"name": "Quantum gravity"}])
assert any("Quantum gravity" in e for e in check(bad, SYL))
derived = tax(ok["subjects"][0]["topics"] + [{"name": "Quantum gravity", "derived": True}])
assert check(derived, SYL) == []
# dropping syllabus wording must be reported
short = tax([{"name": "Matrices"}, {"name": "Calculus"}])
assert any("not covered" in e and "integration" in e for e in check(short, SYL))
# one alias meaning two topics must be refused
dup = tax([{"name": "Matrices", "aliases": ["m"]}, {"name": "determinants", "aliases": ["m"]},
           {"name": "Calculus"}, {"name": "Limits"}, {"name": "integration"}])
assert any("alias 'm'" in e for e in check(dup, SYL))
print("load_taxonomy: all tests passed")
