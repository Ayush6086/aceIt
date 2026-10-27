"""Tests for tools/import_keys.py:  python3 -I tools/test_import_keys.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from import_keys import parse_key, KeyError_, ROW

def bad(q, raw):
    try: parse_key(q, raw)
    except KeyError_: return True
    return False

assert parse_key("MCQ", "B") == ("mcq", {"choice": "B"})
assert parse_key("MSQ", "B;D") == ("msq", {"choices": ["B", "D"]})
assert parse_key("MSQ", "D,B, C") == ("msq", {"choices": ["B", "C", "D"]})          # order and spaces do not matter
assert parse_key("NAT", "-2.1 to -1.9") == ("nat", {"min": -2.1, "max": -1.9})
assert parse_key("NAT", "21 to 21") == ("nat", {"min": 21.0, "max": 21.0})
assert parse_key("MCQ", "MTA") == ("mta", None) and parse_key("NAT", "mta") == ("mta", None)
assert parse_key("MSQ", "A, C, D or C, D") == ("msq", {"any_of": [{"choices": ["A", "C", "D"]}, {"choices": ["C", "D"]}]})
assert parse_key("NAT", "2 to 2 OR 4 to 4") == ("nat", {"any_of": [{"min": 2.0, "max": 2.0}, {"min": 4.0, "max": 4.0}]})
# things that must be refused, not guessed
assert bad("MCQ", "E") and bad("MCQ", "A;B") and bad("MSQ", "B;Z") and bad("NAT", "abc")
assert bad("NAT", "5 to 3") and bad("MCQ", "21 to 21") and bad("NAT", "B")
# a data row, with and without the Session column
assert ROW.match("  29   1   NAT   CS-1   21 to 21   1").groups() == ("29", "1", "NAT", "CS-1", "21 to 21", "1")
assert ROW.match("1 MCQ GA D 1").groups() == ("1", None, "MCQ", "GA", "D", "1")
assert ROW.match("not a row") is None
from import_keys import normalise, infer_type, TWO, ORS_ROW
assert normalise("\u20102 to \u20102") == "-2 to -2" and normalise("B   Marks to All  C") == "B   MTA  C"
assert parse_key("NAT", "11.0 : 11.0") == ("nat", {"min": 11.0, "max": 11.0})                       # 2016 style
assert infer_type("B") == "MCQ" and infer_type("28 to 30") == "NAT" and infer_type("A;C") == "MSQ"  # no Type column (2013, 2014)
assert TWO.findall(" GA        1           B           1        CS      24            C          1") == [("GA","1","B","1"),("CS","24","C","1")]
assert TWO.findall(" CS      26        28 to 30       2") == [("CS","26","28 to 30","2")]
assert ORS_ROW.match("CS     26           A             MTA            B                  C").groups() == ("26","A","MTA","B","C")
print("import_keys: all parser tests passed")
