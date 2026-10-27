import unittest

from aceit.analytics.analysis import analyze
from aceit.analytics.progress import predicted_band, percentile


def row(pos, topic, marks, outcome, t, typ="MCQ", sec="CS"):
    awarded = {"correct": marks, "awarded_to_all": marks, "unattempted": 0, "wrong": -marks / 3 if typ == "MCQ" else 0}[outcome]
    return dict(position=pos, section=sec, type=typ, marks=marks, topic=topic, outcome=outcome, marks_awarded=round(awarded, 2), time_spent_s=t)


class Analysis(unittest.TestCase):
    def sample(self):
        r = [row(1, "operating-system/deadlock", 2, "wrong", 20), row(2, "operating-system/deadlock", 1, "wrong", 15),
             row(3, "operating-system/threads", 2, "correct", 200), row(4, "operating-system/threads", 2, "correct", 190),
             row(5, "databases/normal-forms", 2, "unattempted", 0), row(6, "databases/normal-forms", 2, "unattempted", 0),
             row(7, "databases/sql", 1, "unattempted", 0), row(8, "algorithms/sorting", 2, "wrong", 900),
             row(9, "general-aptitude/verbal-ability", 1, "correct", 60, sec="GA"), row(10, "algorithms/sorting", 1, "correct", 70),
             row(11, "x/y", 1, "correct", 5, "NAT"), dict(row(12, "x/y", 1, "correct", 0), outcome="not_scored")]
        return r

    def test_marks(self):
        m = analyze(self.sample())["marks"]
        self.assertEqual(m["left_unattempted"], 5)
        self.assertEqual(m["unattempted_questions"], 3)
        self.assertAlmostEqual(m["lost_to_negative_marking"], 2 / 3 + 1 / 3 + 2 / 3, places=2)
        self.assertEqual(m["possible"], 2 + 1 + 2 + 2 + 2 + 2 + 1 + 2 + 1 + 1 + 1)          # the not_scored row is left out

    def test_topics_sorted_by_marks_lost(self):
        a = analyze(self.sample())
        order = [t["key"] for t in a["topics"]]
        self.assertEqual(order[0], "databases/normal-forms")                                 # 4 marks, all skipped
        nf = a["topics"][0]
        self.assertEqual((nf["unattempted"], nf["marks_lost"], nf["accuracy"]), (2, 4, None))
        d = next(t for t in a["topics"] if t["key"] == "operating-system/deadlock")
        self.assertEqual((d["wrong"], d["accuracy"]), (2, 0.0))
        subj = {s["key"]: s for s in a["subjects"]}
        self.assertEqual(subj["operating-system"]["correct"], 2)

    def test_time_findings(self):
        t = analyze(self.sample())["time"]
        self.assertEqual([q["position"] for q in t["slow"]], [8])                           # 900 s on a 2-mark question
        self.assertEqual({q["position"] for q in t["rushed_wrong"]}, {1, 2})                # wrong in 20 s and 15 s
        self.assertEqual(t["by_section"]["GA"]["attempted"], 1)

    def test_insights_and_next_practice(self):
        a = analyze(self.sample())
        kinds = [i["kind"] for i in a["insights"]]
        self.assertIn("skipped", kinds); self.assertIn("negative", kinds); self.assertIn("weak", kinds); self.assertIn("rushed", kinds)
        self.assertIn("strong", kinds)                                                       # threads: 2 of 2 right
        self.assertEqual([n["topic"] for n in a["next_practice"]][0], "databases/normal-forms")
        self.assertLessEqual(len(a["next_practice"]), 3)
        self.assertTrue(all(isinstance(i["text"], str) and i["text"] for i in a["insights"]))

    def test_a_perfect_attempt_has_nothing_to_fix(self):
        a = analyze([row(i, "algorithms/sorting", 1, "correct", 60) for i in range(1, 7)])
        self.assertEqual(a["next_practice"], [])
        self.assertEqual([i["kind"] for i in a["insights"]], ["strong"])
        self.assertEqual(analyze([])["marks"]["possible"], 0)                                # an empty attempt does not crash


class Progress(unittest.TestCase):
    BP = {"subject_marks": {"algorithms": {"target": 40}, "databases": {"target": 45}}, "sections": {"GA": {"marks": 15}}}

    def test_percentile(self):
        self.assertIsNone(percentile(50, []))
        p = percentile(50, [10, 20, 50, 60])
        self.assertEqual((p["percentile"], p["rank_estimate"], p["cohort_size"], p["confidence"]), (62.5, 2, 4, "low"))   # ties count half
        self.assertEqual(percentile(99, [1] * 40)["confidence"], "ok")
        self.assertEqual(percentile(0, [5, 6])["percentile"], 0.0)

    def test_band_needs_enough_evidence_and_widens_with_less(self):
        few = {"algorithms": {"earned": 5, "possible": 10, "questions": 8}}
        self.assertIsNone(predicted_band(few, self.BP))
        s = lambda n: {"algorithms": {"earned": 0.7 * n, "possible": n, "questions": n}, "databases": {"earned": 0.4 * n, "possible": n, "questions": n},
                       "general-aptitude": {"earned": 0.6 * n, "possible": n, "questions": n}}
        a, b = predicted_band(s(30), self.BP), predicted_band(s(300), self.BP)
        self.assertTrue(a["low"] < a["mid"] < a["high"])
        self.assertLess(b["high"] - b["low"], a["high"] - a["low"])                          # more evidence, tighter band
        self.assertAlmostEqual(b["mid"], 40 * 0.7 + 45 * 0.4 + 15 * 0.6, delta=1.5)
        self.assertTrue(0 <= a["low"] and a["high"] <= 100)


if __name__ == "__main__":
    unittest.main()


from aceit.analytics.analysis import classify, why_summary, difficulty_label


class Why(unittest.TestCase):
    def test_reasons(self):
        rows = [row(1, "a/x", 1, "correct", 60), row(2, "a/x", 1, "correct", 60), row(3, "a/x", 1, "correct", 60),
                row(4, "a/x", 2, "wrong", 20),                      # fast: silly
                row(5, "a/x", 1, "wrong", 100),                     # normal pace, topic otherwise strong: careless
                row(6, "b/y", 2, "wrong", 900),                     # very long: slow
                row(7, "b/y", 1, "wrong", 100),                     # weak topic, normal pace: concept
                row(8, "c/z", 1, "unattempted", 0),                 # skipped (later questions were touched)
                row(9, "c/z", 1, "correct", 50),
                row(10, "c/z", 1, "unattempted", 0), row(11, "c/z", 1, "unattempted", 0)]   # nothing touched from here on: not reached
        got = classify(rows)
        self.assertEqual({p: got[p] for p in (4, 5, 6, 7, 8, 10, 11)}, {4: "silly", 5: "careless", 6: "slow", 7: "concept", 8: "skipped", 10: "not_reached", 11: "not_reached"})
        self.assertNotIn(1, got)                                    # right answers have no reason
        w = {d["reason"]: d for d in why_summary(rows, got)}
        self.assertEqual(w["not_reached"]["questions"], 2)
        self.assertAlmostEqual(w["silly"]["marks_lost"], 2 + 2 / 3, places=2)    # 2 marks not earned plus 2/3 lost
        self.assertTrue(all(d["advice"] for d in w.values()))
        self.assertEqual(why_summary(rows, got)[0]["marks_lost"], max(d["marks_lost"] for d in w.values()))   # biggest first

    def test_difficulty_needs_enough_students(self):
        self.assertIsNone(difficulty_label(0.2, 5))
        self.assertIsNone(difficulty_label(None, 50))
        self.assertEqual([difficulty_label(r, 30) for r in (0.9, 0.7, 0.5, 0.39)], ["easy", "easy", "medium", "hard"])

    def test_analyze_returns_why(self):
        from aceit.analytics.analysis import analyze
        a = analyze([row(1, "a/x", 2, "wrong", 10), row(2, "a/x", 1, "unattempted", 0)])
        self.assertEqual({p["reason"] for p in a["per_question"]}, {"silly", "not_reached"})
        self.assertTrue(a["why"])
