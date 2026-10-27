import { api, loadImage } from "./api.js";
import { h, clear, say } from "./dom.js";
import * as L from "./logic.js";
import { prefsButtons } from "./prefs.js";

let teardown = null;
export function leaveExam() { if (teardown) { teardown(); teardown = null; } removeEventListener("beforeunload", warn); document.querySelectorAll(".modal").forEach((m) => m.remove()); }
const warn = (e) => { e.preventDefault(); e.returnValue = ""; };

const LEGEND = [["not_visited", "Not visited"], ["not_answered", "Not answered"], ["answered", "Answered"], ["marked", "Marked for review"], ["answered_marked", "Answered + marked"]];
const SECTION_NAME = { GA: "General Aptitude", CS: "Computer Science" };

export async function examView(app, attemptId) {
  document.body.classList.add("exam");
  const a = await api(`/attempts/${attemptId}`);
  if (a.status !== "in_progress") { location.hash = `#/result/${attemptId}`; return; }

  const qs = a.questions;
  let state = L.stateFromServer(qs, a.responses);
  const dirty = new Set();
  let idx = 0, seq = (a.last_seq ?? -1) + 1, saving = false, failures = 0, retryTimer = null, closing = false, enteredAt = Date.now();
  let offset = Date.parse(a.server_now) - Date.now();
  const deadline = Date.parse(a.deadline_at);
  let lastSec = L.remainingSeconds(deadline, Date.now(), offset);

  const timerEl = h("div", { class: "timer", role: "timer", "aria-label": "Time remaining" });
  const saveEl = h("span", { class: "chipsave", "aria-live": "off" }, "Saved ✓");
  const paceEl = h("span", { class: "pace", title: "Marks covered so far compared with the real exam's rate of 108 seconds per mark" });
  const paneEl = h("section", { class: "qpane", "aria-label": "Question" });
  const sideEl = h("aside", { class: "side", "aria-label": "Question palette" });
  const secEl = h("div", { class: "row", role: "group", "aria-label": "Sections" });
  const root = h("div", { id: "main" },
    h("div", { class: "bar" }, h("strong", { text: a.kind === "full" ? "Full mock" : "Topic test" }), secEl, h("span", { class: "grow" }), paceEl, saveEl, prefsButtons(h),
      h("button", { class: "btn ghost", "aria-pressed": "false", "aria-controls": "pad", onclick: (e) => { const on = togglePad(); e.currentTarget.setAttribute("aria-pressed", String(on)); } }, "Rough work"),
      h("button", { class: "btn ghost", "aria-pressed": "false", "aria-controls": "calc", onclick: (e) => { const on = toggleCalc(); e.currentTarget.setAttribute("aria-pressed", String(on)); } }, "Calculator"), timerEl,
      h("button", { class: "btn", onclick: () => askSubmit() }, "Submit")),
    h("div", { class: "console" }, paneEl, sideEl));
  clear(app).append(root);
  addEventListener("beforeunload", warn);

  const entry = (q) => (state[q.id] ||= { visited: false, response: null, marked: false, time: 0 });
  const touch = (q) => dirty.add(q.id);

  // ---- time on the current question
  function bankTime() {
    const q = qs[idx];
    if (!document.hidden) entry(q).time += (Date.now() - enteredAt) / 1000;
    enteredAt = Date.now();
  }
  function go(i) {
    bankTime(); touch(qs[idx]); padSave();
    idx = L.nextIndex(idx, qs.length, i - idx);
    entry(qs[idx]).visited = true; touch(qs[idx]);
    drawAll(); padLoad(); flush();
  }

  // ---- autosave: batch, sequence number, retry with backoff; the server's clock wins
  async function flush() {
    if (saving || closing || dirty.size === 0) return;
    bankTime();
    const ids = new Set(dirty); dirty.clear();
    const batch = L.pendingBatch(qs, state, ids);
    saving = true; saveEl.className = "chipsave"; saveEl.textContent = "Saving…";
    try {
      const r = await api(`/attempts/${attemptId}/responses`, { method: "PUT", body: { seq: seq++, items: batch } });
      offset = (deadline - r.remaining_s * 1000) - Date.now();
      failures = 0; saveEl.textContent = "Saved ✓";
    } catch (e) {
      if (e.status === 409) { closing = true; location.hash = `#/result/${attemptId}`; return; }
      ids.forEach((x) => dirty.add(x)); seq--;
      if (e.status === 422) { dirty.clear(); saveEl.className = "chipsave bad"; saveEl.textContent = "A save was rejected. Reload the page."; }
      else { failures++; saveEl.className = "chipsave bad"; saveEl.textContent = "Offline: your answers are kept here and will retry"; clearTimeout(retryTimer); retryTimer = setTimeout(flush, L.backoffMs(failures)); }
    } finally { saving = false; }
  }
  const saveTimer = setInterval(flush, 8000);

  // ---- timer
  async function expire() {
    if (closing) return; closing = true;
    say("Time is up. Submitting your test.");
    try { await finish(); } catch { location.hash = `#/result/${attemptId}`; }
  }
  const startedAt = Date.parse(a.started_at), totalS = (deadline - startedAt) / 1000, totalMarks = qs.reduce((t, q) => t + q.marks, 0);
  function drawPace() {                                                       // marks of the questions already moved past, against the clock
    const done = qs.reduce((t, q, i) => t + (i !== idx && state[q.id]?.visited ? q.marks : 0), 0);
    const p = L.paceStatus({ elapsedS: (Date.now() + offset - startedAt) / 1000, totalS, totalMarks, marksDone: done });
    paceEl.textContent = `Pace: ${L.paceText(p)}`; paceEl.className = "pace " + p.state;
  }
  const tick = () => {
    drawPace();
    const s = L.remainingSeconds(deadline, Date.now(), offset);
    timerEl.textContent = L.clock(s); timerEl.className = "timer " + (L.timerMood(s) === "low" ? "low" : "");
    const w = L.warningToSpeak(lastSec, s); if (w) say(w);
    lastSec = s; if (s <= 0) expire();
  };
  tick(); const clockTimer = setInterval(tick, 1000);

  // ---- submit
  async function finish() {
    clearInterval(saveTimer); clearInterval(clockTimer); clearTimeout(retryTimer);
    bankTime(); touch(qs[idx]);
    for (let n = 0; n < 4 && dirty.size; n++) { saving = false; closing = false; await flush(); if (location.hash.startsWith("#/result")) return; await new Promise((r) => setTimeout(r, 400)); }
    closing = true;
    removeEventListener("beforeunload", warn);
    await api(`/attempts/${attemptId}/submit`, { method: "POST" });
    location.hash = `#/result/${attemptId}`;
  }
  function askSubmit() {
    bankTime();
    const s = L.summarize(qs, state);
    const close = () => modal.remove();
    const modal = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "dt" },
      h("div", { class: "dialog stack" }, h("h2", { id: "dt", text: "Submit your test?" }),
        h("p", {}, `Answered: ${s.answeredTotal} · Not answered: ${s.not_answered + s.not_visited} · Marked for review: ${s.marked + s.answered_marked}`),
        h("p", { class: "sub", text: "You cannot change your answers after you submit." }),
        h("div", { class: "row" }, h("button", { class: "btn ghost", onclick: close }, "Keep working"),
          h("button", { class: "btn", onclick: async (e) => { e.target.disabled = true; try { await finish(); } catch (x) { close(); saveEl.className = "chipsave bad"; saveEl.textContent = x.message; } } }, "Submit now"))));
    document.body.append(modal); modal.querySelector(".btn.ghost").focus();
  }

  // ---- calculator: a floating panel, not a dialog, so the exam stays usable behind it
  let calcEl = null;
  function toggleCalc() {
    if (calcEl) { calcEl.remove(); calcEl = null; return false; }
    let deg = true, ans = 0;
    const disp = h("input", { type: "text", class: "calcdisp", "aria-label": "Calculator expression", autocomplete: "off", spellcheck: "false" });
    const out = h("div", { class: "calcout", role: "status", "aria-live": "polite", text: "0" });
    const modeBtn = h("button", { type: "button", class: "chip on", "aria-pressed": "true" }, "Deg");
    const put = (t) => { disp.value += t; disp.focus(); };
    const equals = () => { try { ans = L.calc(disp.value || "0", deg); out.textContent = String(ans); out.className = "calcout"; } catch (e) { out.textContent = e.message; out.className = "calcout bad"; } };
    modeBtn.onclick = () => { deg = !deg; modeBtn.textContent = deg ? "Deg" : "Rad"; modeBtn.setAttribute("aria-pressed", String(deg)); };
    disp.addEventListener("keydown", (ev) => { ev.stopPropagation(); if (ev.key === "Enter") equals(); });
    const k = (label, fn, cls = "") => h("button", { type: "button", class: cls, onclick: fn }, label);
    const ins = (label, text = label, cls = "") => k(label, () => put(text), cls);
    const rows = [
      ["sin", "cos", "tan", "ln"].map((f) => ins(f, f + "(", "fn")).concat(ins("log", "log(", "fn"), ins("abs", "abs(", "fn")),
      ["asin", "acos", "atan", "√"].map((f) => ins(f, f === "√" ? "sqrt(" : f + "(", "fn")).concat(ins("x²", "^2", "fn"), ins("exp", "exp(", "fn")),
      [ins("(", "("), ins(")", ")"), ins("^"), ins("!"), ins("π", "pi"), ins("e")],
      [ins("7"), ins("8"), ins("9"), ins("÷", "/", "op"), k("⌫", () => { disp.value = disp.value.slice(0, -1); disp.focus(); }, "op"), k("C", () => { disp.value = ""; out.textContent = "0"; out.className = "calcout"; disp.focus(); }, "op")],
      [ins("4"), ins("5"), ins("6"), ins("×", "*", "op"), ins("%", "%", "op"), k("Ans", () => put(String(ans)), "op")],
      [ins("1"), ins("2"), ins("3"), ins("−", "-", "op"), ins("0"), ins(".")],
      [ins("+", "+", "op"), k("=", () => { equals(); disp.focus(); }, "eq")],
    ];
    calcEl = h("section", { class: "calc", id: "calc", role: "group", "aria-label": "Scientific calculator" },
      h("div", { class: "row" }, h("strong", { text: "Calculator" }), h("span", { class: "grow" }), modeBtn), disp, out,
      h("div", { class: "calckeys" }, rows.flat()));
    document.body.append(calcEl); disp.focus();
    return true;
  }

  // ---- rough-work pad: a sketch canvas or typed notes per question. Kept in this browser only, never sent to the server.
  const notes = {};                                   // question id -> { img: dataURL | null, text: string }
  const NKEY = `aceit-pad-${attemptId}`;
  try { Object.assign(notes, JSON.parse(localStorage.getItem(NKEY) || "{}")); } catch { /* private mode: notes live for this page only */ }
  const persist = () => { try { localStorage.setItem(NKEY, JSON.stringify(notes)); } catch { /* too big or blocked: keep in memory */ } };
  let padEl = null, padLoad = () => {}, padSave = () => {};
  function togglePad() {
    if (padEl) { padSave(); padEl.remove(); padEl = null; padLoad = padSave = () => {}; return false; }
    let mode = "draw", erase = false, down = false, last = null;
    const cv = h("canvas", { class: "padcv", width: 640, height: 400, role: "img", "aria-label": "Sketch area for rough work" });
    const ctx = cv.getContext("2d");
    const ta = h("textarea", { class: "padtxt", "aria-label": "Typed rough work", rows: 9, hidden: true });
    const title = h("strong", {});
    const cur = () => (notes[qs[idx].id] ||= { img: null, text: "" });
    padSave = () => { const n = cur(); n.text = ta.value; n.img = cv.toDataURL(); if (n.img === blank) n.img = null; persist(); };
    const blank = cv.toDataURL();
    padLoad = () => {
      title.textContent = `Rough work · Q${idx + 1}`;
      ctx.clearRect(0, 0, cv.width, cv.height); ta.value = cur().text;
      if (cur().img) { const im = new Image(); const id = qs[idx].id; im.onload = () => { if (qs[idx].id === id) ctx.drawImage(im, 0, 0); }; im.src = cur().img; }
    };
    const at = (e) => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]; };
    cv.addEventListener("pointerdown", (e) => { down = true; last = at(e); cv.setPointerCapture(e.pointerId); stroke(last, last); });
    cv.addEventListener("pointermove", (e) => { if (!down) return; const p = at(e); stroke(last, p); last = p; });
    const up = () => { if (down) { down = false; padSave(); } };
    cv.addEventListener("pointerup", up); cv.addEventListener("pointercancel", up);
    function stroke(a, b) {
      ctx.globalCompositeOperation = erase ? "destination-out" : "source-over"; ctx.lineCap = "round"; ctx.lineJoin = "round";
      ctx.lineWidth = erase ? 24 : 3; ctx.strokeStyle = "#000"; ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke();
    }
    ta.addEventListener("input", padSave);
    const chip = (t, on, f) => { const b = h("button", { type: "button", class: "chip" + (on ? " on" : ""), "aria-pressed": String(on), onclick: f }, t); return b; };
    const bar = h("div", { class: "row" });
    const drawBar = () => clear(bar).append(
      chip("Draw", mode === "draw" && !erase, () => { mode = "draw"; erase = false; show(); }), chip("Erase", mode === "draw" && erase, () => { mode = "draw"; erase = true; show(); }),
      chip("Type", mode === "type", () => { mode = "type"; show(); }),
      h("button", { type: "button", class: "chip", onclick: () => { ctx.clearRect(0, 0, cv.width, cv.height); ta.value = ""; padSave(); } }, "Clear"));
    function show() { cv.hidden = mode !== "draw"; ta.hidden = mode !== "type"; drawBar(); if (mode === "type") ta.focus(); }
    const head = h("div", { class: "row padhead", title: "Drag to move" }, title, h("span", { class: "grow" }));
    padEl = h("section", { class: "pad", id: "pad", role: "group", "aria-label": "Rough work pad" }, head, bar, cv, ta);
    head.addEventListener("pointerdown", (e) => {                       // drag the pad anywhere on the screen by its title bar
      const r = padEl.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      head.setPointerCapture(e.pointerId);
      Object.assign(padEl.style, { width: r.width + "px", right: "auto", bottom: "auto" });
      const move = (m) => Object.assign(padEl.style, { left: Math.min(Math.max(0, m.clientX - dx), innerWidth - r.width) + "px", top: Math.min(Math.max(0, m.clientY - dy), innerHeight - 48) + "px" });
      head.addEventListener("pointermove", move);
      head.addEventListener("pointerup", () => head.removeEventListener("pointermove", move), { once: true });
    });
    document.body.append(padEl); show(); padLoad();
    return true;
  }

  // ---- drawing
  function setResponse(q, r) { entry(q).response = r; entry(q).visited = true; touch(q); drawPalette(); }
  function optionButtons(q) {
    const e = entry(q), withText = q.display !== "image" || !q.image_crops;
    const opts = q.options || ["A", "B", "C", "D"].map((l) => ({ label: l, text: "" }));
    return h("div", { class: "options", role: q.type === "MCQ" ? "radiogroup" : "group", "aria-label": q.type === "MCQ" ? "Choose one option" : "Choose one or more options" },
      opts.map((o) => {
        const on = q.type === "MCQ" ? e.response?.choice === o.label : (e.response?.choices || []).includes(o.label);
        return h("button", { class: "opt" + (withText ? "" : " letters"), role: q.type === "MCQ" ? "radio" : "checkbox", "aria-checked": String(on), "data-label": o.label,
          onclick: () => { setResponse(q, q.type === "MCQ" ? (on ? null : { choice: o.label }) : L.isAnswered("MSQ", L.toggleChoice(e.response, o.label)) ? L.toggleChoice(e.response, o.label) : null); drawPane(); } },
          h("b", { text: o.label }), withText ? h("span", { text: o.text }) : null);
      }));
  }
  function natInput(q) {
    const e = entry(q);
    const input = h("input", { class: "natbox", type: "text", inputmode: "decimal", "aria-label": "Your numerical answer", autocomplete: "off", value: e.response?.value ?? "" });
    const set = (t) => { input.value = L.cleanNat(t); setResponse(q, L.natResponse(input.value)); };
    input.addEventListener("input", () => set(input.value));
    const key = (t, f) => h("button", { type: "button", "aria-label": t === "⌫" ? "Backspace" : t, onclick: f || (() => { set(input.value + t); input.focus(); }) }, t);
    return h("div", {}, input, h("div", { class: "keypad", "aria-label": "Number pad" },
      ["7", "8", "9", "⌫", "4", "5", "6", "-", "1", "2", "3", ".", "0", "C"].map((k) => k === "⌫" ? key(k, () => set(input.value.slice(0, -1))) : k === "C" ? key(k, () => set("")) : key(k))));
  }
  function drawPane() {
    const q = qs[idx], e = entry(q);
    const neg = q.type === "MCQ" ? `Negative marking: −${q.marks === 1 ? "1/3" : "2/3"}` : "No negative marking";
    const images = q.display === "image" && q.image_crops ? Array.from({ length: q.image_crops }, (_, n) => { const im = h("img", { class: "crop", alt: `Question ${idx + 1} as printed in the paper`, loading: "lazy" }); loadImage(im, q.id, n); return im; }) : null;
    clear(paneEl).append(
      h("div", { class: "qhead" }, h("span", { class: "qnum", text: `Q${idx + 1}` }), h("span", { class: "tag", text: `${q.marks} mark${q.marks > 1 ? "s" : ""}` }),
        h("span", { class: "tag", text: q.type === "MCQ" ? "One correct" : q.type === "MSQ" ? "One or more correct" : "Numerical answer" }), h("span", { class: "tag", text: neg }), h("span", { class: "tag", text: SECTION_NAME[q.section] })),
      ...(images ?? [h("p", { class: "stem", text: q.stem_md })]),
      q.type === "NAT" ? natInput(q) : optionButtons(q),
      h("div", { class: "actions" },
        h("button", { class: "btn", onclick: () => go(idx + 1) }, "Save & next"),
        h("button", { class: "btn ghost", onclick: () => { entry(q).marked = true; touch(q); go(idx + 1); } }, "Mark for review & next"),
        h("button", { class: "btn ghost", onclick: () => { entry(q).response = null; entry(q).marked = false; touch(q); drawAll(); } }, "Clear response"),
        h("button", { class: "btn ghost", disabled: idx === 0, onclick: () => go(idx - 1) }, "Previous")));
  }
  function drawPalette() {
    const s = L.summarize(qs, state);
    clear(sideEl).append(
      h("div", { class: "label sub", text: `${s.answeredTotal} of ${qs.length} answered` }),
      h("div", { class: "palette" }, qs.map((q, i) => { const st = L.statusOf(state[q.id], q.type);
        return h("button", { class: `pq ${st}${i === idx ? " current" : ""}`, "aria-label": `Question ${i + 1}: ${LEGEND.find((x) => x[0] === st)[1]}`, "aria-current": i === idx ? "true" : null, onclick: () => go(i) }, String(i + 1)); })),
      h("div", { class: "legend" }, LEGEND.map(([k, n]) => h("span", {}, h("i", { class: `pq ${k}`, style: "width:14px;height:14px;display:inline-block" }), `${n} (${s[k]})`))));
    clear(secEl).append(...[...new Set(qs.map((q) => q.section))].map((sec) => h("button", { class: "pill", "aria-pressed": String(qs[idx].section === sec), onclick: () => go(L.firstOfSection(qs, sec)) }, SECTION_NAME[sec])));
  }
  const drawAll = () => { drawPane(); drawPalette(); };

  function onKey(ev) {
    if (ev.target.matches?.("input, select, textarea") || ev.target.closest?.(".calc, .pad") || ev.ctrlKey || ev.metaKey || ev.altKey || document.querySelector(".modal")) return;
    if (ev.key === "ArrowRight") go(idx + 1); else if (ev.key === "ArrowLeft") go(idx - 1);
    else if (/^[a-dA-D]$/.test(ev.key) && qs[idx].type !== "NAT") paneEl.querySelector(`[data-label="${ev.key.toUpperCase()}"]`)?.click();
  }
  addEventListener("keydown", onKey);
  document.addEventListener("visibilitychange", () => { enteredAt = Date.now(); });

  entry(qs[0]).visited = true; touch(qs[0]);
  drawAll(); flush();
  teardown = () => { clearInterval(saveTimer); clearInterval(clockTimer); clearTimeout(retryTimer); removeEventListener("keydown", onKey); closing = true; calcEl?.remove(); padEl?.remove(); };
}
