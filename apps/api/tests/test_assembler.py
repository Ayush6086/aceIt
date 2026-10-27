import json
import unittest
from pathlib import Path

from aceit.testing.assembler import AssemblyError, Candidate, build_full_mock, build_topic_test, validate_plan

DATA = Path(__file__).resolve().parents[3] / "data"
BP = json.loads((DATA / "blueprints" / "gate_cs_v1.json").read_text())
RAW = json.loads((DATA / "pool" / "gate_cs_dev_pool.json").read_text())
# near-duplicate groups: pretend the same question was set in two different years, to test the rule
POOL = [Candidate(r["id"], r["section"], r["marks"], r["type"], r["subject"], r["topic"], "", r["rank_eligible"]) for r in RAW]
BY_ID = {c.id: c for c in POOL}


class Assembler(unittest.TestCase):
    def test_pool_and_blueprint_are_what_we_expect(self):
        self.assertEqual(len(POOL), 975)
        self.assertEqual(BP["total_marks"], 100)
        self.assertGreaterEqual(sum(1 for c in POOL if c.rank_eligible), 200)

    def test_full_mock_meets_the_blueprint(self):
        for seed in range(25):
            plan = build_full_mock(POOL, BP, seed, rank_only=False)
            qs = [BY_ID[i] for i in plan.question_ids]
            self.assertEqual(validate_plan(qs, BP, rank_only=False, relaxed=plan.relaxed), [], seed)
            self.assertEqual(len(set(plan.question_ids)), 65)
            self.assertEqual([q.section for q in qs[:10]], ["GA"] * 10)
            self.assertEqual([q.marks for q in qs[:5]], [1] * 5)                    # GATE order: 1-mark questions first
            self.assertEqual([q.marks for q in qs[10:35]], [1] * 25)
            self.assertFalse(plan.relaxed)

    def test_same_seed_same_test_different_seed_different_test(self):
        a = build_full_mock(POOL, BP, 7, rank_only=False).question_ids
        self.assertEqual(a, build_full_mock(POOL, BP, 7, rank_only=False).question_ids)
        tests = {tuple(build_full_mock(POOL, BP, s, rank_only=False).question_ids) for s in range(10)}
        self.assertEqual(len(tests), 10)

    def test_a_student_does_not_see_a_question_twice_while_unseen_ones_exist(self):
        seen = set()
        for s in range(5):                                                           # five tests in a row for one student
            plan = build_full_mock(POOL, BP, s, seen=frozenset(seen), rank_only=False)
            self.assertEqual(plan.stats["seen_reused"], 0, s)
            seen |= set(plan.question_ids)
        self.assertEqual(len(seen), 5 * 65)

    def test_rank_test_uses_only_rank_eligible_questions(self):
        plan = build_full_mock(POOL, BP, 3, rank_only=True)
        self.assertTrue(all(BY_ID[i].rank_eligible for i in plan.question_ids))
        # the validator refuses a rank test that contains anything else
        mixed = [BY_ID[i] for i in plan.question_ids]
        mixed[20] = next(c for c in POOL if not c.rank_eligible and c.section == "CS" and c.marks == mixed[20].marks and c.subject == mixed[20].subject)
        self.assertTrue(any("rank-eligible" in p for p in validate_plan(mixed, BP, rank_only=True, relaxed=True)))

    def test_near_duplicates_never_share_a_test(self):
        pool = [Candidate(c.id, c.section, c.marks, c.q_type, c.subject, c.topic, f"g{i % 150}", True) for i, c in enumerate(POOL)]
        for seed in range(5):
            plan = build_full_mock(pool, BP, seed, rank_only=False)
            groups = [next(c.dup_group for c in pool if c.id == i) for i in plan.question_ids]
            self.assertEqual(len(groups), len(set(groups)))

    def test_validator_catches_a_bad_test(self):
        plan = build_full_mock(POOL, BP, 1, rank_only=False)
        qs = [BY_ID[i] for i in plan.question_ids]
        self.assertTrue(any("65" in p for p in validate_plan(qs[:60], BP, rank_only=False)))
        self.assertTrue(any("twice" in p for p in validate_plan(qs[:64] + [qs[0]], BP, rank_only=False)))
        broken = qs[:]                                        # a 2-mark question where a 1-mark one belongs: split and total break
        broken[10] = next(c for c in POOL if c.section == "CS" and c.marks == 2 and c.id not in plan.question_ids)
        problems = validate_plan(broken, BP, rank_only=False)
        self.assertTrue(any("section CS" in p for p in problems) and any("marks add up" in p for p in problems), problems)

    def test_impossible_requests_fail_loudly_not_with_a_broken_test(self):
        tiny = [c for c in POOL if c.subject != "databases"][:300]                    # a pool with no database questions at all
        with self.assertRaises(AssemblyError):
            build_full_mock(tiny, BP, 1, rank_only=False, max_tries=20)

    def test_topic_test(self):
        ids = build_topic_test(POOL, {"operating-system/deadlock"}, 5, seed=1)
        self.assertTrue(0 < len(ids) <= 5 and all(BY_ID[i].topic == "operating-system/deadlock" for i in ids))
        subj = build_topic_test(POOL, {"databases"}, 20, seed=1)                      # a subject includes everything under it
        self.assertEqual(len(subj), 20)
        self.assertTrue(all(BY_ID[i].subject == "databases" for i in subj))
        parent = build_topic_test(POOL, {"algorithms/algorithm-design-techniques"}, 10, seed=2)
        self.assertTrue(all(BY_ID[i].topic.startswith("algorithms/algorithm-design-techniques/") for i in parent))
        self.assertEqual(build_topic_test(POOL, {"databases"}, 20, seed=1), subj)     # reproducible
        with self.assertRaises(AssemblyError):
            build_topic_test(POOL, {"no-such-topic"}, 5, seed=1)


if __name__ == "__main__":
    unittest.main()
