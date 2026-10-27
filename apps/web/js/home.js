import { api, session } from "./api.js";
import { h, clear } from "./dom.js";
import { header } from "./main.js";
import { percent } from "./logic.js";
import { startTest, kindLabel } from "./start.js";

const SUBJECTS = [["Engineering Mathematics", "engineering-mathematics"], ["Digital Logic", "digital-logic"], ["Computer Organization", "computer-organization-and-architecture"],
  ["Programming & Data Structures", "programming-and-data-structures"], ["Algorithms", "algorithms"], ["Theory of Computation", "theory-of-computation"],
  ["Compiler Design", "compiler-design"], ["Operating System", "operating-system"], ["Databases", "databases"], ["Computer Networks", "computer-networks"]];

async function begin(body, errBox) {
  errBox.hidden = true;
  try {
    const t = await api("/tests", { method: "POST", body });
    const a = await api("/attempts", { method: "POST", body: { test_id: t.id } });
    location.hash = `#/exam/${a.id}`;
  } catch (e) { errBox.hidden = false; errBox.textContent = e.status === 422 ? `Couldn't build that test: ${e.message}` : e.message; }
}

const niceTopic = (slug) => slug.split("/").pop().replaceAll("-", " ");

/** Privacy tools: download everything we hold about the student, or erase it. */
function yourData() {
  const msg = h("p", { class: "sub", role: "status" });
  const download = async () => {
    try {
      const blob = new Blob([JSON.stringify(await api("/me/export"), null, 2)], { type: "application/json" });
      const a = h("a", { href: URL.createObjectURL(blob), download: "aceit-my-data.json" }); a.click();
    } catch (e) { msg.textContent = e.message; }
  };
  const erase = async () => {
    if (!confirm("Delete your aceIt data? Your tests, answers, notes and bookmarks are erased for good. This cannot be undone.")) return;
    try { await api("/me", { method: "DELETE" }); session.clear(); location.hash = "#/"; location.reload(); } catch (e) { msg.textContent = e.message; }
  };
  return h("section", { class: "card span-12", "aria-labelledby": "yd" }, h("h2", { id: "yd", text: "Your data" }),
    h("div", { class: "row" }, h("button", { class: "btn ghost", onclick: download }, "Download my data"), h("button", { class: "btn ghost", onclick: erase }, "Delete my data")), msg);
}

export async function homeView(app) {
  const [attempts, notebook, marked] = await Promise.all([api("/attempts"), api("/me/mistakes").catch(() => ({ count: 0, topics: [] })), api("/me/bookmarks").catch(() => ({ count: 0 }))]);
  const done = attempts.filter((a) => a.score !== null && a.score !== undefined);
  const best = done.length ? Math.max(...done.map((a) => a.score)) : null;
  const open = attempts.find((a) => a.status === "in_progress");
  const correct = done.reduce((s, a) => s + (a.correct || 0), 0), wrong = done.reduce((s, a) => s + (a.wrong || 0), 0);

  let mode = "sprint";
  const selected = new Map();                              // slug -> name
  const errBox = h("p", { class: "notice err", role: "alert", hidden: true });
  const matches = h("div", { class: "row", "aria-live": "polite" });
  const chosen = h("div", { class: "row" });
  const search = h("input", { type: "search", id: "topic", placeholder: "Type a topic: deadlock, dp, b+ tree…", "aria-label": "Topic name", autocomplete: "off", maxlength: "80" });
  const count = h("select", { "aria-label": "Number of questions" }, [10, 20, 30].map((n) => h("option", { value: n }, `${n} questions`)));
  const body = h("div", { class: "stack" });

  const drawChosen = () => {
    clear(chosen).append(...[...selected].map(([slug, name]) => h("button", { class: "chip on", title: "Remove", onclick: () => { selected.delete(slug); drawChosen(); } }, `${name} ✕`)));
  };
  const add = (slug, name) => { selected.set(slug, name); drawChosen(); };
  async function find() {
    const q = search.value.trim(); if (!q) return;
    const r = await api(`/topics/resolve?q=${encodeURIComponent(q)}`);
    clear(matches).append(...(r.matches.length ? r.matches.map((m) => h("button", { class: "chip", onclick: () => add(m.slug, m.name) }, `+ ${m.name}`))
      : [h("span", { class: "sub" }, `No syllabus topic matches “${q}”. Try another word, or pick a subject below.`)]));
  }
  search.addEventListener("keydown", (e) => e.key === "Enter" && find().catch((x) => (errBox.hidden = false, errBox.textContent = x.message)));

  function drawBody() {
    clear(body);
    if (mode === "topic") {
      body.append(
        h("div", { class: "row" }, search, h("button", { class: "btn ghost", onclick: () => find().catch((x) => (errBox.hidden = false, errBox.textContent = x.message)) }, "Find")),
        matches,
        h("div", { class: "row" }, SUBJECTS.map(([n, s]) => h("button", { class: "chip", onclick: () => add(s, n) }, n))),
        chosen,
        h("div", { class: "row" }, count, h("button", { class: "btn lime go", onclick: () => selected.size ? begin({ kind: "topic", topics: [...selected.keys()], count: +count.value }, errBox) : (errBox.hidden = false, errBox.textContent = "Pick at least one topic first.") }, "Start test")));
    } else if (mode === "sprint") {
      const subj = h("select", { "aria-label": "Subject" }, h("option", { value: "" }, "Mixed: all subjects"), SUBJECTS.map(([n, sl]) => h("option", { value: sl }, n)));
      const len = h("select", { "aria-label": "Length" }, [[10, "Sprint: 10 questions (about 25 min)"], [20, "Subject test: 20 questions"], [30, "Long test: 30 questions"]].map(([v, t]) => h("option", { value: v }, t)));
      body.append(
        h("div", { class: "row" }, subj, len),
        h("div", { class: "row" }, h("button", { class: "btn lime go", onclick: () => begin({ kind: "topic", topics: subj.value ? [subj.value] : SUBJECTS.map((x) => x[1]), count: +len.value }, errBox) }, "Start")));
    } else {
      body.append(
        h("label", { class: "row" }, h("input", { type: "checkbox", id: "rankonly" }), " Ranked questions only"),
        h("div", { class: "row" }, h("button", { class: "btn lime go", onclick: () => { const r = document.getElementById("rankonly").checked; begin({ kind: "full", rank_only: r }, errBox); } }, "Start")));
    }
  }
  const tab = (id, label) => h("button", { class: "pill", "aria-pressed": String(mode === id), onclick: () => { mode = id; errBox.hidden = true; render(); } }, label);

  function render() {
    clear(app).append(h("div", { class: "wrap", id: "main" }, header(session.user),
      h("div", { class: "grid" },
        h("section", { class: "card lime span-7" }, h("div", { class: "stack" },
          h("div", { class: "label", text: "Your prep" }),
          h("h1", { class: "big", text: `Hi ${session.username}, here's your prep.` }),
          h("div", { class: "row" }, h("span", { class: "pill" }, `${attempts.length} test${attempts.length === 1 ? "" : "s"} taken`),
            attempts.length ? h("span", { class: "pill black" }, `${percent(correct, correct + wrong)}% accuracy on answered`) : null),
          open ? h("div", { class: "notice" }, "You have a test in progress. ", h("a", { href: `#/exam/${open.id}`, text: "Resume it →" })) : null)),
        h("section", { class: "card black span-5" }, h("div", { class: "label", text: "Best score" }),
          h("div", { class: "big" }, best === null ? "–" : best.toFixed(2)), h("div", { class: "sub" }, best === null ? "Take a test to see your score here." : "out of the test's total marks")),
        h("section", { class: "card span-8", "aria-labelledby": "ct" }, h("div", { class: "stack" },
          h("h2", { id: "ct", text: "Create a test" }),
          h("div", { class: "tabs", role: "group", "aria-label": "Test type" }, tab("sprint", "Sprint"), tab("topic", "By topic"), tab("full", "Full mock")),
          errBox, body)),
        h("section", { class: "card rose span-4", "aria-labelledby": "nb" }, h("div", { class: "stack" },
          h("div", { class: "label", text: "Retry and improve" }), h("h2", { id: "nb", text: "Mistakes notebook" }),
          notebook.count
            ? h("div", { class: "stack" }, h("div", { class: "big", text: String(notebook.count) }),
                h("p", { text: `question${notebook.count === 1 ? "" : "s"} you got wrong and have not got right since. ` + (notebook.topics[0] ? `Most are in ${niceTopic(notebook.topics[0].topic)}.` : "") }),
                h("button", { class: "btn go", onclick: () => startTest({ kind: "retry", count: 20 }).catch((e) => { errBox.hidden = false; errBox.textContent = e.message; }) }, "Retry my mistakes"))
            : h("p", { text: "No mistakes yet." }),
          marked.count ? h("button", { class: "btn ghost", onclick: () => startTest({ kind: "retry", source: "bookmarks", count: 20 }).catch((e) => { errBox.hidden = false; errBox.textContent = e.message; }) }, `Practise my ${marked.count} bookmark${marked.count === 1 ? "" : "s"}`) : null)),
        h("section", { class: "card span-4", "aria-labelledby": "rt" }, h("h2", { id: "rt", text: "Recent tests" }),
          h("ul", { class: "list" }, attempts.length ? attempts.slice(0, 8).map((a) => h("li", {},
            h("div", { class: "grow" }, h("div", { text: kindLabel(a.kind) }), h("div", { class: "sub" }, new Date(a.started_at).toLocaleString())),
            a.status === "in_progress" ? h("a", { class: "pill cyan", href: `#/exam/${a.id}` }, "Resume")
              : h("a", { class: "pill", href: `#/result/${a.id}` }, a.score === null ? "View" : `${a.score}/${a.max_score}`))) : [h("li", { class: "sub" }, "No tests yet.")])),
        yourData())));
    drawBody(); drawChosen();
  }
  render();
}
