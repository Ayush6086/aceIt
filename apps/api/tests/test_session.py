import unittest
from datetime import datetime, timedelta, timezone

from aceit.session import attempt as at

T0 = datetime(2026, 10, 27, 10, 0, 0, tzinfo=timezone.utc)
sec = lambda s: T0 + timedelta(seconds=s)


class Session(unittest.TestCase):
    def new(self, mult=1.0):
        return at.start_attempt("a1", "u1", T0, 10800, mult)          # 3 hours

    def test_deadline_is_fixed_by_the_server(self):
        a = self.new()
        self.assertEqual(a.deadline_at, sec(10800))
        self.assertEqual(at.remaining_s(a, sec(100)), 10700)
        self.assertEqual(at.remaining_s(a, sec(99999)), 0)
        self.assertEqual(self.new(1.25).deadline_at, sec(13500))       # extra time
        with self.assertRaises(ValueError):
            at.start_attempt("a", "u", T0, 0)

    def test_autosave_is_idempotent_and_ordered(self):
        a = self.new()
        item = lambda q, r, t=5: {"question_id": q, "response": r, "palette_status": "answered", "time_spent_s": t}
        self.assertEqual(at.apply_autosave(a, [item("q1", {"choice": "A"})], 1, sec(10))["reason"], "ok")
        # the same batch again (a retry) and an OLDER batch arriving late change nothing
        self.assertEqual(at.apply_autosave(a, [item("q1", {"choice": "B"})], 1, sec(11))["reason"], "duplicate")
        self.assertEqual(at.apply_autosave(a, [item("q1", {"choice": "C"})], 0, sec(12))["reason"], "duplicate")
        self.assertEqual(a.responses["q1"].response, {"choice": "A"})
        self.assertEqual(at.apply_autosave(a, [item("q1", {"choice": "D"})], 2, sec(13))["reason"], "ok")
        self.assertEqual(a.responses["q1"].response, {"choice": "D"})

    def test_time_spent_only_grows_and_is_capped(self):
        a = self.new()
        at.apply_autosave(a, [{"question_id": "q1", "time_spent_s": 50}], 1, sec(60))
        at.apply_autosave(a, [{"question_id": "q1", "time_spent_s": 10}], 2, sec(70))          # cannot go down
        self.assertEqual(a.responses["q1"].time_spent_s, 50)
        at.apply_autosave(a, [{"question_id": "q1", "time_spent_s": 99999}], 3, sec(80))       # cannot exceed elapsed time
        self.assertEqual(a.responses["q1"].time_spent_s, 80)

    def test_grace_period_and_too_late(self):
        a = self.new()
        r = at.apply_autosave(a, [{"question_id": "q1", "response": {"choice": "A"}}], 1, sec(10800 + 30))
        self.assertTrue(r["accepted"])                                  # exactly at the end of the grace period
        r = at.apply_autosave(a, [{"question_id": "q1", "response": {"choice": "B"}}], 2, sec(10800 + 31))
        self.assertEqual((r["accepted"], r["reason"]), (False, "too_late"))
        self.assertEqual(a.responses["q1"].response, {"choice": "A"})

    def test_validation_rejects_bad_batches_whole(self):
        a = self.new()
        r = at.apply_autosave(a, [{"question_id": "q1", "palette_status": "answered"}, {"question_id": "q9"}], 1, sec(5), allowed_questions={"q1", "q2"})
        self.assertEqual(r["reason"], "unknown_question")
        self.assertEqual(a.responses, {})                               # nothing half-applied
        r = at.apply_autosave(a, [{"question_id": "q1", "palette_status": "hacked"}], 2, sec(6))
        self.assertEqual(r["reason"], "bad_palette_status")
        self.assertEqual(a.last_seq, -1)

    def test_submit_is_idempotent_and_never_counts_past_the_deadline(self):
        a = self.new()
        self.assertEqual(at.submit(a, sec(500)), "submitted")
        self.assertEqual(at.submit(a, sec(900)), "submitted")           # second call changes nothing
        self.assertEqual(a.submitted_at, sec(500))
        self.assertEqual(at.apply_autosave(a, [{"question_id": "q1"}], 1, sec(501))["reason"], "attempt_closed")
        b = self.new()
        self.assertEqual(at.submit(b, sec(10800 + 20)), "submitted")    # inside the grace period
        self.assertEqual(b.submitted_at, sec(10800))
        c = self.new()
        self.assertEqual(at.submit(c, sec(10800 + 600)), "auto_submitted")

    def test_sweeper_closes_only_abandoned_attempts(self):
        live, late, done = self.new(), self.new(), self.new()
        live.id, late.id, done.id = "live", "late", "done"
        at.submit(done, sec(100))
        closed = at.sweep([live, late, done], sec(10800 + 31))
        self.assertEqual({x.id for x in closed}, {"live", "late"})      # both are past deadline + grace
        self.assertTrue(all(x.status == "auto_submitted" and x.submitted_at == sec(10800) for x in closed))
        fresh = self.new()
        self.assertEqual(at.sweep([fresh], sec(10800 + 30)), [])        # still inside the grace period
        self.assertEqual(at.sweep([live], sec(99999)), [])              # an already-closed attempt is left alone

    def test_integrity_only_excludes_from_cohort(self):
        a = self.new()
        self.assertFalse(at.integrity_excludes_from_cohort(a))
        a.integrity["tab_blur"] = 14
        self.assertFalse(at.integrity_excludes_from_cohort(a))
        a.integrity["tab_blur"] = 15
        self.assertTrue(at.integrity_excludes_from_cohort(a))
        b = self.new(); b.integrity["second_session"] = 1
        self.assertTrue(at.integrity_excludes_from_cohort(b))


if __name__ == "__main__":
    unittest.main()
