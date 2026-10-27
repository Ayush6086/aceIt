import test from "node:test";
import assert from "node:assert/strict";
import * as L from "../js/logic.js";

test("answered, by type", () => {
  assert.equal(L.isAnswered("MCQ", { choice: "A" }), true);
  assert.equal(L.isAnswered("MCQ", { choice: "" }), false);
  assert.equal(L.isAnswered("MSQ", { choices: [] }), false);
  assert.equal(L.isAnswered("MSQ", { choices: ["B"] }), true);
  assert.equal(L.isAnswered("NAT", { value: "0" }), true);          // zero is an answer
  assert.equal(L.isAnswered("NAT", { value: " " }), false);
  assert.equal(L.isAnswered("NAT", null), false);
});

test("palette status", () => {
  assert.equal(L.statusOf(undefined, "MCQ"), "not_visited");
  assert.equal(L.statusOf({ visited: true }, "MCQ"), "not_answered");
  assert.equal(L.statusOf({ visited: true, response: { choice: "A" } }, "MCQ"), "answered");
  assert.equal(L.statusOf({ visited: true, marked: true }, "MCQ"), "marked");
  assert.equal(L.statusOf({ visited: true, marked: true, response: { choice: "A" } }, "MCQ"), "answered_marked");
});

test("multiple select toggles and stays sorted", () => {
  let r = L.toggleChoice(null, "C");
  r = L.toggleChoice(r, "A");
  assert.deepEqual(r.choices, ["A", "C"]);
  r = L.toggleChoice(r, "C");
  assert.deepEqual(r.choices, ["A"]);
});

test("numeric entry", () => {
  assert.equal(L.cleanNat("12abc.5"), "12.5");
  assert.equal(L.cleanNat("-2.1"), "-2.1");
  assert.equal(L.natResponse(""), null);
  assert.deepEqual(L.natResponse("3.5"), { value: "3.5" });
  assert.equal(L.cleanNat("1".repeat(40)).length, 24);
});

test("time comes from the server clock, never below zero", () => {
  const deadline = 1_000_000;
  assert.equal(L.remainingSeconds(deadline, 900_000, 0), 100);
  assert.equal(L.remainingSeconds(deadline, 900_000, 50_000), 50);     // the client clock is 50 s behind the server
  assert.equal(L.remainingSeconds(deadline, 2_000_000, 0), 0);
  assert.equal(L.clock(10800), "03:00:00");
  assert.equal(L.clock(59), "00:00:59");
});

test("timer mood and spoken warnings", () => {
  assert.equal(L.timerMood(601), "ok");
  assert.equal(L.timerMood(600), "low");
  assert.equal(L.warningToSpeak(1801, 1800), "30 minutes remaining");
  assert.equal(L.warningToSpeak(1800, 1799), null);                     // spoken once, not every second
  assert.equal(L.warningToSpeak(601, 600), "10 minutes remaining");
  assert.equal(L.warningToSpeak(301, 300), "5 minutes remaining");
  assert.equal(L.warningToSpeak(5000, 4000), null);
});

test("summary and autosave batch", () => {
  const qs = [{ id: "a", type: "MCQ" }, { id: "b", type: "NAT" }, { id: "c", type: "MSQ" }, { id: "d", type: "MCQ" }];
  const st = { a: { visited: true, response: { choice: "B" }, time: 12.4 }, b: { visited: true, marked: true }, c: { visited: true, marked: true, response: { choices: ["A"] } } };
  const s = L.summarize(qs, st);
  assert.deepEqual([s.answered, s.marked, s.answered_marked, s.not_visited], [1, 1, 1, 1]);
  assert.equal(s.answeredTotal, 2); assert.equal(s.unanswered, 2);
  const batch = L.pendingBatch(qs, st, new Set(["a", "b", "d"]));
  assert.deepEqual(batch.map((x) => [x.question_id, x.palette_status, x.response]), [["a", "answered", { choice: "B" }], ["b", "marked", null], ["d", "not_answered", null]]);
  assert.equal(batch[0].time_spent_s, 12);
});

test("sections, navigation, retry delay, resume", () => {
  const qs = [{ id: "a", section: "GA" }, { id: "b", section: "CS" }, { id: "c", section: "CS" }];
  assert.equal(L.firstOfSection(qs, "CS"), 1);
  assert.equal(L.nextIndex(2, 3, 1), 2); assert.equal(L.nextIndex(0, 3, -1), 0); assert.equal(L.nextIndex(0, 3, 1), 1);
  assert.deepEqual([0, 1, 2, 9].map(L.backoffMs), [1000, 2000, 4000, 30000]);
  const st = L.stateFromServer(qs, { b: { response: { choice: "A" }, palette_status: "answered_marked", time_spent_s: 40 } });
  assert.deepEqual(st.b, { visited: true, response: { choice: "A" }, marked: true, time: 40 });
  assert.equal(st.a, undefined);
  assert.equal(L.percent(1, 3), 33); assert.equal(L.percent(1, 0), 0);
});

test("calculator: precedence, functions, angle modes, and bad input", () => {
  assert.equal(L.calc("2+3*4"), 14);
  assert.equal(L.calc("-2^2"), -4);
  assert.equal(L.calc("2^3^2"), 512);
  assert.equal(L.calc("(1+2)*3/4"), 2.25);
  assert.equal(L.calc("5!"), 120);
  assert.equal(L.calc("sin(30)"), 0.5);
  assert.equal(L.calc("sin(180)"), 0);
  assert.equal(L.calc("cos(pi)", false), -1);
  assert.equal(L.calc("asin(1)"), 90);
  assert.equal(L.calc("log(1000)+ln(e)+sqrt(16)"), 8);
  assert.equal(L.calc("0.1+0.2"), 0.3);
  assert.equal(L.calc("10 % 3"), 1);
  for (const bad of ["", "2+", "(1", "1/0", "foo(2)", "alert(1)", "2 3", "(-1)!", "1.5!"]) assert.throws(() => L.calc(bad), /Invalid/, bad);
});

test("pace compares marks covered with the real exam's rate", () => {
  const base = { totalS: 10800, totalMarks: 100 };
  assert.equal(L.paceStatus({ ...base, elapsedS: 0, marksDone: 0 }).state, "on");
  assert.equal(L.paceStatus({ ...base, elapsedS: 5400, marksDone: 50 }).state, "on");            // half the time, half the marks
  const behind = L.paceStatus({ ...base, elapsedS: 5400, marksDone: 30 });
  assert.deepEqual([behind.state, behind.marks, behind.minutes], ["behind", 20, 36]);              // 20 marks short = 36 minutes at 108 s per mark
  assert.equal(L.paceText(behind), "36 min behind");
  const ahead = L.paceStatus({ ...base, elapsedS: 1800, marksDone: 40 });
  assert.equal(ahead.state, "ahead"); assert.equal(L.paceText(ahead), "42 min ahead");
  assert.equal(L.paceStatus({ ...base, elapsedS: 20000, marksDone: 100 }).state, "on");            // time over: expected capped at the full paper
  assert.equal(L.paceStatus({ totalS: 600, totalMarks: 6, elapsedS: 300, marksDone: 0 }).state, "behind");   // short tests work too
});
