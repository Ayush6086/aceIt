// Pure logic of the exam console: no DOM, no network, so it can be tested on its own (tests/logic.test.mjs).

export const PALETTE = ["not_visited", "not_answered", "answered", "marked", "answered_marked"];

/** Has the student put in an answer? */
export function isAnswered(type, r) {
  if (!r) return false;
  if (type === "MCQ") return !!r.choice;
  if (type === "MSQ") return Array.isArray(r.choices) && r.choices.length > 0;
  if (type === "NAT") return r.value !== undefined && r.value !== null && String(r.value).trim() !== "";
  return false;
}

/** Palette status of a question from what the student has done. */
export function statusOf(entry, type) {
  if (!entry || !entry.visited) return "not_visited";
  const answered = isAnswered(type, entry.response);
  if (entry.marked) return answered ? "answered_marked" : "marked";
  return answered ? "answered" : "not_answered";
}

/** Toggle one option of a multiple-select answer, keeping the letters sorted. */
export function toggleChoice(current, letter) {
  const set = new Set(current?.choices || []);
  set.has(letter) ? set.delete(letter) : set.add(letter);
  return { choices: [...set].sort() };
}

/** NAT: accept only what can be a number while typing: digits, one dot, a leading minus, an exponent. */
export function cleanNat(text) {
  const t = String(text).replace(/[^0-9.\-eE]/g, "");
  return t.length > 24 ? t.slice(0, 24) : t;
}

export function natResponse(text) {
  const t = cleanNat(text);
  if (t === "") return null;
  return { value: t };                       // sent as typed; the server compares numerically
}

/** Seconds left, from the SERVER's clock: offset = serverNow - clientNow, measured when the page last heard from the server. */
export function remainingSeconds(deadlineMs, clientNowMs, offsetMs) {
  return Math.max(0, Math.ceil((deadlineMs - (clientNowMs + offsetMs)) / 1000));
}

export function clock(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const p = (n) => String(n).padStart(2, "0");
  return `${p(h)}:${p(m)}:${p(s)}`;
}

/** Timer state: calm until the last 10 minutes, then a rose pill. Spoken warnings only at 30, 10 and 5 minutes. */
export function timerMood(sec) { return sec <= 600 ? "low" : "ok"; }
export function warningToSpeak(prevSec, sec) {
  for (const m of [30, 10, 5]) if (prevSec > m * 60 && sec <= m * 60) return `${m} minutes remaining`;
  return null;
}

/** Counts for the palette legend and the submit dialog. */
export function summarize(questions, state) {
  const c = { not_visited: 0, not_answered: 0, answered: 0, marked: 0, answered_marked: 0 };
  for (const q of questions) c[statusOf(state[q.id], q.type)]++;
  return { ...c, answeredTotal: c.answered + c.answered_marked, unanswered: c.not_visited + c.not_answered + c.marked };
}

/** What to send on the next autosave: everything touched since the last successful save. */
export function pendingBatch(questions, state, dirty) {
  return questions.filter((q) => dirty.has(q.id)).map((q) => ({
    question_id: q.id,
    response: isAnswered(q.type, state[q.id]?.response) ? state[q.id].response : null,
    palette_status: statusOf(state[q.id], q.type) === "not_visited" ? "not_answered" : statusOf(state[q.id], q.type),
    time_spent_s: Math.round(state[q.id]?.time || 0),
  }));
}

/** First question of a section, for the GA / CS pills. */
export function firstOfSection(questions, section) {
  const i = questions.findIndex((q) => q.section === section);
  return i < 0 ? 0 : i;
}

export function nextIndex(i, n, step) { return Math.min(n - 1, Math.max(0, i + step)); }

/** Retry delay for a failed autosave: 2s, 4s, 8s ... never more than 30s. */
export function backoffMs(failures) { return Math.min(30000, 1000 * 2 ** Math.min(failures, 5)); }

/** Rebuild the local state from what the server remembers (resume after a reload). */
export function stateFromServer(questions, responses) {
  const state = {};
  for (const q of questions) {
    const r = responses[q.id];
    if (!r) continue;
    state[q.id] = { visited: r.palette_status !== "not_visited", response: r.response, marked: r.palette_status === "marked" || r.palette_status === "answered_marked", time: r.time_spent_s || 0 };
  }
  return state;
}

export function percent(a, b) { return b > 0 ? Math.round((a / b) * 100) : 0; }

// ---- scientific calculator: a small parser, never eval(). deg=true means sin/cos/tan take and asin/acos/atan give degrees.
const FUNCS = { sin: Math.sin, cos: Math.cos, tan: Math.tan, asin: Math.asin, acos: Math.acos, atan: Math.atan, log: Math.log10, ln: Math.log, sqrt: Math.sqrt, cbrt: Math.cbrt, exp: Math.exp, abs: Math.abs, log2: Math.log2 };
const TRIG_IN = new Set(["sin", "cos", "tan"]), TRIG_OUT = new Set(["asin", "acos", "atan"]);

export function calc(text, deg = true) {
  const toks = String(text).replace(/×/g, "*").replace(/÷/g, "/").replace(/π/g, "pi").replace(/√/g, "sqrt").match(/\d+\.?\d*(?:e[+-]?\d+)?|\.\d+|[a-z][a-z0-9]*|\S/gi) || [];
  let p = 0;
  const peek = () => toks[p], next = () => toks[p++];
  const fail = () => { throw new Error("Invalid expression"); };
  const expr = () => { let v = term(); while (peek() === "+" || peek() === "-") v = next() === "+" ? v + term() : v - term(); return v; };
  const term = () => { let v = unary(); while (peek() === "*" || peek() === "/" || peek() === "%") { const o = next(), r = unary(); v = o === "*" ? v * r : o === "/" ? v / r : v % r; } return v; };
  const unary = () => (peek() === "-" ? (next(), -unary()) : peek() === "+" ? (next(), unary()) : power());
  const power = () => { const b = postfix(); return peek() === "^" ? (next(), Math.pow(b, unary())) : b; };
  const postfix = () => { let v = primary(); while (peek() === "!") { next(); if (!Number.isInteger(v) || v < 0 || v > 170) fail(); let f = 1; for (let i = 2; i <= v; i++) f *= i; v = f; } return v; };
  const primary = () => {
    const t = next();
    if (t === undefined) fail();
    if (/^[\d.]/.test(t)) { const n = Number(t); if (Number.isNaN(n)) fail(); return n; }
    if (t === "(") { const v = expr(); if (next() !== ")") fail(); return v; }
    const k = t.toLowerCase();
    if (k === "pi") return Math.PI;
    if (k === "e") return Math.E;
    if (FUNCS[k]) { if (next() !== "(") fail(); const a = expr(); if (next() !== ")") fail(); const x = TRIG_IN.has(k) && deg ? a * Math.PI / 180 : a, y = FUNCS[k](x); return TRIG_OUT.has(k) && deg ? y * 180 / Math.PI : y; }
    return fail();
  };
  const v = expr();
  if (p < toks.length || !Number.isFinite(v)) fail();
  return Math.abs(v) < 1e-12 ? 0 : Number(v.toPrecision(12));
}

// ---- pace: are you covering the paper at the real exam's rate (108 seconds per mark)?
/** marksDone = marks of the questions already moved past. Returns {state: 'on' | 'ahead' | 'behind', marks, minutes}. */
export function paceStatus({ elapsedS, totalS, totalMarks, marksDone }) {
  const expected = totalMarks * Math.min(1, Math.max(0, elapsedS) / totalS);
  const gap = marksDone - expected;                       // + ahead, - behind
  const marks = Math.round(Math.abs(gap));
  const minutes = Math.round((Math.abs(gap) * (totalS / totalMarks)) / 60);
  const slack = Math.max(2, totalMarks * 0.03);           // a couple of marks either way still counts as on pace
  return { state: Math.abs(gap) <= slack ? "on" : gap > 0 ? "ahead" : "behind", marks, minutes };
}
export const paceText = (p) => (p.state === "on" ? "On pace" : p.state === "ahead" ? `${p.minutes} min ahead` : `${p.minutes} min behind`);
