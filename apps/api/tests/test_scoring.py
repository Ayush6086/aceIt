"""Scoring rules. Run:  PYTHONPATH=src python3 -I -m unittest discover -s tests -v"""
import unittest
from fractions import Fraction as F

from aceit.scoring.marks import score_question as sq
from aceit.scoring.attempt import Item, score_attempt


class Marks(unittest.TestCase):
    def test_mcq(self):
        k = {"choice": "B"}
        self.assertEqual(sq("MCQ", 1, "mcq", k, {"choice": "B"}).marks, F(1))
        self.assertEqual(sq("MCQ", 1, "mcq", k, {"choice": "A"}).marks, F(-1, 3))      # 1-mark wrong = -1/3
        self.assertEqual(sq("MCQ", 2, "mcq", k, {"choice": "A"}).marks, F(-2, 3))      # 2-mark wrong = -2/3
        o = sq("MCQ", 2, "mcq", k, None)
        self.assertEqual((o.marks, o.status, o.max_marks), (F(0), "unattempted", F(2)))
        self.assertEqual(sq("MCQ", 1, "mcq", k, {"choice": ""}).status, "unattempted")

    def test_msq_is_all_or_nothing_without_negative_marks(self):
        k = {"choices": ["B", "D"]}
        self.assertEqual(sq("MSQ", 2, "msq", k, {"choices": ["D", "B"]}).marks, F(2))   # order does not matter
        for wrong in (["B"], ["B", "C", "D"], ["A"]):
            o = sq("MSQ", 2, "msq", k, {"choices": wrong})
            self.assertEqual((o.marks, o.status), (F(0), "wrong"))

    def test_nat_range_is_inclusive_and_never_negative(self):
        k = {"min": 1.9, "max": 2.1}
        for v in (1.9, 2, 2.1, "2.0"):
            self.assertEqual(sq("NAT", 1, "nat", k, {"value": v}).marks, F(1), v)
        for v in (1.89, 2.11, "abc"):
            self.assertEqual(sq("NAT", 1, "nat", k, {"value": v}).marks, F(0), v)
        self.assertEqual(sq("NAT", 1, "nat", k, {"value": ""}).status, "unattempted")
        self.assertEqual(sq("NAT", 1, "nat", {"min": -2.1, "max": -1.9}, {"value": -2}).marks, F(1))

    def test_alternative_answers(self):
        k = {"any_of": [{"choices": ["A", "C", "D"]}, {"choices": ["C", "D"]}]}
        self.assertEqual(sq("MSQ", 1, "msq", k, {"choices": ["C", "D"]}).marks, F(1))
        self.assertEqual(sq("MSQ", 1, "msq", k, {"choices": ["A", "C", "D"]}).marks, F(1))
        self.assertEqual(sq("MSQ", 1, "msq", k, {"choices": ["A", "C"]}).marks, F(0))
        n = {"any_of": [{"min": 2, "max": 2}, {"min": 4, "max": 4}]}
        self.assertEqual(sq("NAT", 1, "nat", n, {"value": 4}).marks, F(1))

    def test_marks_to_all_and_dropped(self):
        for resp in (None, {"choice": "A"}):                       # even if unattempted or "wrong"
            o = sq("MCQ", 1, "mta", None, resp)
            self.assertEqual((o.marks, o.status), (F(1), "awarded_to_all"))
        o = sq("MCQ", 2, "dropped", None, {"choice": "A"})
        self.assertEqual((o.marks, o.max_marks, o.status), (F(0), F(0), "not_scored"))

    def test_scheme_override(self):
        self.assertEqual(sq("MCQ", 2, "mcq", {"choice": "A"}, {"choice": "B"}, {"mcq_negative_fraction": F(1, 4)}).marks, F(-1, 2))

    def test_exact_arithmetic(self):
        # 3 wrong 1-mark MCQs lose exactly 1 mark in total: no 0.9999999 from floats
        total = sum((sq("MCQ", 1, "mcq", {"choice": "A"}, {"choice": "B"}).marks for _ in range(3)), F(0))
        self.assertEqual(total, F(-1))


class Attempt(unittest.TestCase):
    def test_totals_sections_topics(self):
        mk = lambda i, sec, t, m, kt, key, topic, resp: Item(i, sec, t, m, kt, key, topic, resp)
        items = [
            mk("q1", "GA", "MCQ", 1, "mcq", {"choice": "A"}, "verbal", {"choice": "A"}),          # +1
            mk("q2", "GA", "MCQ", 2, "mcq", {"choice": "A"}, "numerical", {"choice": "B"}),       # -2/3
            mk("q3", "CS", "NAT", 2, "nat", {"min": 5, "max": 5}, "os/deadlock", {"value": 5}),   # +2
            mk("q4", "CS", "MSQ", 1, "msq", {"choices": ["A"]}, "os/deadlock", None),             # 0, unattempted
            mk("q5", "CS", "MCQ", 1, "mta", None, "os/threads", None),                            # +1 to all
            mk("q6", "CS", "MCQ", 1, "dropped", None, "os/threads", {"choice": "A"}),             # not counted
        ]
        r = score_attempt(items)
        self.assertEqual(r.score, F(1) - F(2, 3) + 2 + 1)
        self.assertEqual(r.max_score, F(1 + 2 + 2 + 1 + 1))                                        # dropped is not in the total
        self.assertEqual(r.counts, {"correct": 2, "wrong": 1, "unattempted": 1, "awarded_to_all": 1, "not_scored": 1})
        self.assertEqual(r.by_section["GA"], (F(1, 3), F(3)))
        self.assertEqual(r.by_topic["os/deadlock"][2:], (1, 0, 1))                                 # 1 correct, 0 wrong, 1 unattempted
        self.assertNotIn("os/threads", {k for k in r.by_topic if r.by_topic[k][1] == 0})
        self.assertEqual(r.as_json()["score"], 3.33)


if __name__ == "__main__":
    unittest.main()
