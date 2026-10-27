import { api, session, loadImage } from "./api.js";
import { h, clear } from "./dom.js";
import { header } from "./main.js";
import { percent, clock } from "./logic.js";
import { startTest } from "./start.js";
import { mathNode } from "./math.js";

const NAMES = { "general-aptitude": "General Aptitude", "engineering-mathematics": "Engineering Mathematics", "digital-logic": "Digital Logic", "computer-organization-and-architecture": "Computer Organization",
  "programming-and-data-structures": "Programming & Data Structures", algorithms: "Algorithms", "theory-of-computation": "Theory of Computation", "compiler-design": "Compiler Design",
  "operating-system": "Operating System", databases: "Databases", "computer-networks": "Computer Networks" };
const nice = (slug) => (NAMES[slug.split("/")[0]] || slug) + (slug.includes("/") ? " › " + slug.split("/").slice(1).join(" › ").replaceAll("-", " ") : "");

const bar = (ok, no, none) => { const t = ok + no + none || 1;
  return h("div", { class: "stackbar", role: "img", "aria-label": `${ok} correct, ${no} wrong, ${none} not attempted` },
    h("i", { class: "ok", style: `width:${(ok / t) * 100}%` }), h("i", { class: "no", style: `width:${(no / t) * 100}%` }), h("i", { class: "hatch", style: `width:${(none / t) * 100}%` })); };

const showKey = (r) => { if (!r) return "–"; return r.choice ?? (r.choices ? r.choices.join(", ") : r.value ?? "–"); };
const keyText = (q) => q.key_type === "mta" ? "Marks to all" : q.key_type === "dropped" ? "Dropped" : q.key?.any_of ? q.key.any_of.map(showKey).join("  or  ") : q.key?.min !== undefined ? (q.key.min === q.key.max ? q.key.min : `${q.key.min} to ${q.key.max}`) : showKey(q.key);

const kindName = (k) => (k === "custom" ? "retry" : k === "pyq" ? "past paper" : k === "topic" ? "topic test" : "full mock");
const REASON_CHIP = { silly: "Answered too fast", careless: "Careless slip", slow: "Took very long", concept: "Concept gap", skipped: "Skipped", not_reached: "Ran out of time" };
const explainBody = (text) => {                              // plain text at once, typeset maths a moment later
  const box = h("div", {}, h("p", { class: "stem", text }));
  mathNode(text, "p", "stem").then((n) => box.replaceChildren(n)).catch(() => {});
  return box;
};
const noteBlock = (q) => {                                   // bookmark and a private note, saved as you go
  let bm = !!q.bookmarked;
  const b = h("button", { class: "chip" + (bm ? " on" : ""), type: "button", "aria-pressed": String(bm) }, bm ? "★ Bookmarked" : "☆ Bookmark");
  const status = h("span", { class: "sub", role: "status" });
  b.onclick = async () => { const want = !bm; try { await api(`/questions/${q.id}/note`, { method: "PUT", body: { bookmarked: want } }); bm = want; b.className = "chip" + (bm ? " on" : ""); b.setAttribute("aria-pressed", String(bm)); b.textContent = bm ? "★ Bookmarked" : "☆ Bookmark"; status.textContent = ""; } catch { status.textContent = "Could not save"; } };
  const ta = h("textarea", { class: "padtxt", rows: 2, maxlength: "2000", placeholder: "Your private note for this question…", "aria-label": "Your private note" }); ta.value = q.note || "";
  ta.addEventListener("blur", async () => { if (ta.value === (q.note || "")) return; try { await api(`/questions/${q.id}/note`, { method: "PUT", body: { note: ta.value } }); q.note = ta.value; status.textContent = "Note saved"; } catch { status.textContent = "Could not save the note"; } });
  return h("div", { class: "stack" }, h("div", { class: "row" }, b, status), ta);
};
const reportButton = (q) => { const b = h("button", { class: "chip", type: "button" }, "Report a problem with this question");
  b.onclick = async () => { b.disabled = true; try { const r = await api(`/questions/${q.id}/report`, { method: "POST", body: { detail: "" } }); b.textContent = r.recorded ? "Thanks, reported" : "You already reported this"; } catch (e) { b.disabled = false; b.textContent = "Could not send. Try again"; } };
  return b; };

export async function resultView(app, id) {
  const [res, review, an] = await Promise.all([api(`/attempts/${id}/result`), api(`/attempts/${id}/review`), api(`/attempts/${id}/analysis`)]);
  const c = res.counts, attempted = (c.correct || 0) + (c.wrong || 0), acc = percent(c.correct || 0, attempted);
  const topics = Object.entries(res.by_topic).sort((a, b) => (b[1].max - b[1].score) - (a[1].max - a[1].score));
  const subj = {};
  for (const [slug, t] of topics) { const s = slug.split("/")[0]; const o = (subj[s] ||= { score: 0, max: 0, correct: 0, wrong: 0, none: 0 }); o.score += t.score; o.max += t.max; o.correct += t.correct; o.wrong += t.wrong; o.none += t.unattempted; }
  const why = Object.fromEntries((an.per_question ?? []).map((p) => [p.position, p.reason]));
  const filter = { v: "all" };
  const list = h("div", {});
  const drawList = () => {
    clear(list).append(...review.filter((q) => filter.v === "all" || (filter.v === "wrong" ? q.outcome === "wrong" : q.outcome === "unattempted")).map((q) => {
      const det = h("details", { class: "reviewq" },
        h("summary", {}, h("b", { text: `Q${q.position} ` }), h("span", { class: q.outcome === "correct" || q.outcome === "awarded_to_all" ? "good" : q.outcome === "wrong" ? "bad" : "sub", text: ({ correct: "Correct", wrong: "Wrong", unattempted: "Not attempted", awarded_to_all: "Marks to all", not_scored: "Not scored" })[q.outcome] }),
          ` · ${q.marks_awarded > 0 ? "+" : ""}${q.marks_awarded} · ${nice(q.topic || "–")} `,
            why[q.position] ? h("span", { class: "chip", text: REASON_CHIP[why[q.position]] }) : null, q.difficulty ? h("span", { class: "chip", title: `${Math.round(q.correct_rate * 100)}% of students got it right`, text: q.difficulty }) : null),
        h("div", { class: "stack" }, q.display === "image" && q.image_crops ? Array.from({ length: q.image_crops }, (_, n) => { const im = h("img", { class: "crop", alt: `Question ${q.position}`, loading: "lazy" }); loadImage(im, q.id, n); return im; }) : h("p", { class: "stem", text: q.stem_md }),
          h("p", {}, "Your answer: ", h("b", { text: q.response ? showKey(q.response) : "not answered" }), "   Official answer: ", h("b", { text: keyText(q) })),
          q.explanation ? h("div", { class: "explain" }, h("div", { class: "explain-label", text: "Explanation" }), explainBody(q.explanation),
            h("p", { class: "sub", text: "Written by AI and checked against the official answer. If it looks wrong, report it below." }))
            : h("p", { class: "sub", text: "No written explanation for this question yet." }),
          noteBlock(q), reportButton(q)));
      return det;
    }));
    if (!list.children.length) list.append(h("p", { class: "sub", text: "Nothing to show here." }));
  };
  const f = (v, t) => h("button", { class: "chip" + (filter.v === v ? " on" : ""), onclick: () => { filter.v = v; drawList(); drawChips(); } }, t);
  const chips = h("div", { class: "row" });
  const drawChips = () => clear(chips).append(f("all", "All questions"), f("wrong", "Wrong only"), f("unattempted", "Not attempted"));

  const scoreCard = h("section", { class: "card black span-5" }, h("div", { class: "label", text: "Your score" }),
    h("div", { class: "big" }, res.score.toFixed(2), h("span", { class: "sub", text: ` / ${res.max_score}` })),
    h("div", { class: "sub", text: res.rank_eligible ? "Counts towards rank (official final answer keys)." : "Practice result: not ranked." }));
  const accCard = h("section", { class: "card lime span-3" }, h("div", { class: "label", text: "Accuracy on attempted" }),
    h("div", { class: "big", text: `${acc}%` }), h("div", { class: "sub", text: `${c.correct || 0} right of ${attempted} attempted` }));
  const countCard = h("section", { class: "card span-4" }, h("div", { class: "label", text: "All questions" }), bar(c.correct || 0, c.wrong || 0, c.unattempted || 0),
    h("div", { class: "sub", style: "margin-top:10px", text: `${c.correct || 0} correct · ${c.wrong || 0} wrong · ${c.unattempted || 0} not attempted` }),
    c.awarded_to_all ? h("div", { class: "sub", text: `${c.awarded_to_all} question(s) gave marks to everyone.` }) : null);

  const sectionRows = Object.entries(res.by_section).map(([k, v]) =>
    h("tr", {}, h("td", { text: k === "GA" ? "General Aptitude (section)" : "Subject part (section)" }), h("td", { text: `${v.score.toFixed(2)} / ${v.max}` }), h("td"), h("td")));
  const subjectRows = Object.entries(subj).sort((a, b) => (b[1].max - b[1].score) - (a[1].max - a[1].score)).map(([s, v]) =>
    h("tr", {}, h("td", { text: NAMES[s] || s }), h("td", { text: `${v.score.toFixed(2)} / ${v.max}` }),
      h("td", { text: `${v.correct} right, ${v.wrong} wrong, ${v.none} skipped` }), h("td", { style: "width:35%" }, bar(v.correct, v.wrong, v.none))));
  const marksCard = h("section", { class: "card span-12" }, h("h2", { text: "Where your marks went" }),
    h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", { text: "Subject" }), h("th", { text: "Marks" }), h("th", { text: "Questions" }), h("th", { text: "" }))),
      h("tbody", {}, sectionRows, subjectRows)),
    h("p", { class: "sub", text: "Sorted by marks lost. The hatched part is questions you did not attempt." }));
  const me = (await api("/attempts")).find((a) => a.id === id);
  let pairCard = null;
  if (me?.pair_id) {
    const sets = (await api(`/test-pairs/${me.pair_id}`)).sets, both = sets.every((x) => x.status === "submitted" || x.status === "auto_submitted");
    const next = sets.find((x) => x.status === undefined || x.status === null || x.status === "in_progress");
    const go = async (x) => { const a = await api("/attempts", { method: "POST", body: { test_id: x.test_id } }); location.hash = `#/exam/${a.id}`; };
    pairCard = both
      ? h("section", { class: "card lime span-12" }, h("h2", { text: "Both papers done" }), h("p", { text: `Combined: ${sets.reduce((t, x) => t + x.score, 0).toFixed(2)} / ${sets.reduce((t, x) => t + x.max_score, 0)}. Each paper is marked on its own.` }))
      : next ? h("section", { class: "card lime span-12" }, h("h2", { text: "Your other paper" }), h("button", { class: "btn", onclick: () => go(next).catch(() => {}) }, next.attempt_id ? "Resume" : "Start")) : null;
  }
  const min = (s) => Math.round(s / 60);
  const coh = an.cohort;
  const insightCard = h("section", { class: "card span-8" }, h("h2", { text: "What the numbers say" }),
    (an.insights ?? []).length ? h("ul", { class: "stack" }, (an.insights ?? []).map((i) => h("li", { text: i.text }))) : h("p", { class: "sub", text: "Nothing stands out. Take a few more tests to see patterns." }),
    h("p", { class: "sub", text: `Time used: ${min(an.time.used_s)} min against about ${min(an.time.expected_s)} min for these marks.` }));
  const fail = h("p", { class: "notice err", role: "alert", hidden: true });
  const run = (body) => startTest(body).catch((e) => { fail.hidden = false; fail.textContent = e.message; });
  const nextCard = h("section", { class: "card rose span-4" }, h("h2", { text: "Practise next" }),
    (an.next_practice ?? []).length ? h("ul", { class: "list" }, (an.next_practice ?? []).map((n) => h("li", {}, h("div", { class: "grow" }, h("b", { text: nice(n.topic) }), h("div", { class: "sub", text: `${n.marks_lost} marks lost` })),
        h("button", { class: "chip", onclick: () => run({ kind: "topic", topics: [n.topic], count: 10 }) }, "Practise 10 →"))))
      : h("p", { text: "No weak topic in this test." }),
    h("button", { class: "btn ghost", style: "margin-top:12px", onclick: () => run({ kind: "retry", count: 20 }) }, "Retry my mistakes"), fail,
    coh ? h("p", { class: "sub", text: `Estimated rank ${coh.rank_estimate} of ${coh.cohort_size + 1} (${coh.percentile}th percentile)${coh.confidence === "low" ? ", small group so treat as rough" : ""}.` }) : null);
  const vp = an.vs_previous;
  const whyCard = h("section", { class: "card span-12" }, h("div", { class: "label", text: "Why you lost marks" }),
    (an.why ?? []).length ? h("div", { class: "whygrid" }, (an.why ?? []).map((w) => h("div", { class: "whyitem" }, h("div", { class: "lnum2", text: String(w.marks_lost) }), h("div", { class: "whylabel", text: `${w.label} · ${w.questions} question${w.questions === 1 ? "" : "s"}` }), h("p", { class: "sub", text: w.advice }))))
      : h("p", { text: "You did not lose marks in this test." }),
    vp ? h("p", { class: "sub", style: "margin-top:14px", text: `Compared with your previous ${kindName(me?.kind)}: ${vp.percent_before}% → ${vp.percent_now}% (${vp.change >= 0 ? "+" : ""}${vp.change} points), wrong answers ${vp.wrong_before} → ${vp.wrong_now}, skipped ${vp.skipped_before} → ${vp.skipped_now}.` }) : null);
  const reviewCard = h("section", { class: "card span-12" }, h("h2", { text: "Review your answers" }), chips, list,
    h("p", { class: "sub", text: "Official answer keys are from the exam organisers. Written explanations are AI-generated and are being added question by question." }));

  const grid = h("div", { class: "grid" }, scoreCard, accCard, countCard, marksCard, whyCard, pairCard, insightCard, nextCard, reviewCard);
  const again = h("div", { class: "row", style: "margin-top:16px" }, h("a", { class: "btn lime go", href: "#/" }, "Take another test"));
  clear(app).append(h("div", { class: "wrap", id: "main" }, header(session.user), grid, again));
  drawChips(); drawList();
}
