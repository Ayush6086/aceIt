// The signed-out front door. Everything shown as a figure is a real fact about the product (62 syllabus topics, 180-minute papers,
// 100 marks); mock-ups are labelled as examples and show no invented user counts, ratings or logos.
import { h, clear } from "./dom.js";
import { prefsButtons } from "./prefs.js";


// Each answer states what the product does today. Keep them true: change the answer when the product changes.
const FAQ = [
  ["Is it really free?", "Yes. Creating an account and taking tests costs nothing, and there are no ads."],
  ["Where do the questions come from?", "From past GATE Computer Science papers between 2013 and 2026. Not every year is in yet: we add a year once its paper and official answer key have been checked. Full mocks are built from 2018 onwards, which matches the current exam format; older years are used in topic tests. Papers before 2013 are not included."],
  ["Are the answers official?", "Tests are scored against the answer keys published by the exam organisers. If a paper's key is not yet marked final, tests using it are practice only and are not ranked."],
  ["How is a test marked?", "Like the real exam. A wrong single-choice answer costs one third of the question's marks (1/3 for a 1-mark question, 2/3 for a 2-mark question). Multi-select questions need exactly the right set of options and have no negative marking. Numerical answers are accepted inside the official range and have no negative marking."],
  ["Can I pause a test or close the browser?", "You can close the page and come back: your answers are saved as you go and the test resumes where you left off. The clock keeps running on our side, like a real exam, and the test is submitted automatically when time is up."],
  ["How accurate is the rank estimate?", "It compares your score with other students' best scores on the same kind of ranked full mock. With few students it is rough, and it is labelled that way. It is an estimate for practice, not a prediction of your real GATE rank."],
  ["Is there a calculator?", "Yes. The exam screen has a scientific calculator and a rough-work pad for drawing or typing notes. Rough work stays on your device and is never sent to us."],
  ["What if a question or answer looks wrong?", "Use \u201CReport a problem\u201D on any question in your review. When several students report the same question and an automatic check does not support its answer key, it is removed from new tests."],
  ["What do you do with my details?", "You sign in with your email on a secure Amazon Cognito page, and we never see your password. We keep your test history so you can review it and see your analysis."],
  ["Are you part of GATE?", "No. aceIt is an independent practice site and is not affiliated with GATE or the institutes that organise it."],
];

const go = () => { location.hash = "#/login"; };
const scrollTo = (id) => document.getElementById(id)?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
const eyebrow = (t) => h("div", { class: "eyebrow" }, t);
const cta = (label = "Start for free") => h("button", { class: "btn lime go", onclick: go }, label);

function phone() {                                             // an exam-console preview drawn in CSS; sample content, not a screenshot
  const opt = (l, t, on) => h("div", { class: "pmo" + (on ? " on" : "") }, h("b", { text: l }), h("span", { text: t }));
  const pal = ["answered", "answered", "marked", "not_answered", "answered", "", "", "answered", "", ""];
  return h("div", { class: "phone", role: "img", "aria-label": "Preview of the exam screen: timer, question, four options and a question palette" },
    h("div", { class: "pnotch" }),
    h("div", { class: "pscr" },
      h("div", { class: "prow" }, h("span", { class: "pclock", text: "02:41:08" }), h("span", { class: "ptag", text: "Q12 · 2 marks" })),
      h("p", { class: "pq-text", text: "Which condition is necessary for a deadlock to occur?" }),
      opt("A", "Preemption of resources"), opt("B", "Circular wait", true), opt("C", "A single process"), opt("D", "No shared resources"),
      h("div", { class: "ppal" }, pal.map((s, i) => h("i", { class: s }, String(i + 1)))),
      h("div", { class: "pbtn", text: "Save & next →" })));
}

export function landingView(app, cfg = {}) {
  document.body.classList.remove("exam");
  const nav = h("header", { class: "lnav" },
    h("a", { class: "logo", href: "#/", "aria-label": "aceIt home" }, h("i"), "aceIt"),
    h("nav", { class: "lnav-links", "aria-label": "Sections" }, [["how", "How it works"], ["features", "Features"], ["faq", "FAQ"], ["start", "Start"]].map(([id, t]) => h("button", { class: "pill", onclick: () => scrollTo(id) }, t))),
    prefsButtons(h), h("button", { class: "btn ghost", onclick: go }, "Login / Sign up"));

  const hero = h("section", { class: "lhero" },
    h("div", { class: "lhero-copy stack" },
      eyebrow("GATE CS · free mock tests"),
      h("h1", { class: "hero", text: "Sit the exam before the exam" }),
      h("p", { class: "lead", text: "Timed GATE Computer Science mock tests built from past papers, scored with the real marking rules, with a clear picture of where every mark went." }),
      h("div", { class: "row" }, cta(), h("button", { class: "btn ghost", onclick: () => scrollTo("how") }, "See how it works")),
      h("p", { class: "lproof" }, h("b", { text: "100% free." }), " Official answer keys. No card, no ads.")),
    h("div", { class: "lhero-art" }, phone()));

  const strip = h("div", { class: "lstrip", role: "list" }, ["Official answer keys", "Negative marking", "Numerical + multi-select", "Free"].map((t) => h("span", { role: "listitem", text: t })));

  const about = h("section", { class: "labout", id: "how" },
    eyebrow("About"),
    h("p", { class: "lstatement" }, "Take timed mocks built from real GATE papers, see exactly where your marks go, and keep every practice session ", h("span", { class: "dim", text: "grounded in the official answer keys, with the exam's real shape: 65 questions, 100 marks, 3 hours." }))
  );
  // numbered cards (the reference's 01 / 02 / 03 row)
  const cards = h("div", { class: "lcards" }, [["01", "Full mocks", "180", "minutes, the real length"], ["02", "Topic tests", "62", "syllabus topics to drill"], ["03", "Marks analysis", "100", "marks, every one traced", "forest"], ["04", "Paired papers", "2", "sets, like CS1 and CS2"]].map(([k, name, n, l, tone]) =>
    h("div", { class: "lcard " + (tone || "") }, h("div", { class: "lkey" }, h("span", { class: "lk", text: k }), name), h("div", { class: "lnum", text: n }), h("div", { class: "lname", text: l }))));
  about.append(cards);

  const row = (flip, tag, title, text, visual, btn) => h("section", { class: "lfeat" + (flip ? " flip" : ""), id: tag === "Build" ? "features" : null },
    h("div", { class: "lfeat-art" }, visual),
    h("div", { class: "lfeat-copy stack" }, eyebrow(tag), h("h2", { class: "ltitle", text: title }), h("p", { class: "lead", text: text }), btn || null));

  const buildMock = h("div", { class: "mini", role: "img", "aria-label": "Example of creating a topic test" },
    h("div", { class: "mrow" }, h("div", { class: "mfield", text: "deadlock" }), h("div", { class: "mbtn", text: "FIND" })),
    h("div", { class: "mrow wrap" }, ["Operating System › deadlock", "Databases", "+ Algorithms"].map((t, i) => h("span", { class: "mchip" + (i === 0 ? " on" : ""), text: t }))),
    h("div", { class: "mrow" }, h("span", { class: "mselect", text: "20 questions" }), h("span", { class: "mgo", text: "START TEST →" })));

  const analysisMock = h("div", { class: "mini", role: "img", "aria-label": "Example of a result analysis" },
    h("div", { class: "mlabel", text: "Example result" }),
    h("div", { class: "mbig" }, "54.33", h("small", { text: " / 100" })),
    h("div", { class: "mbar" }, h("i", { class: "ok", style: "width:52%" }), h("i", { class: "no", style: "width:18%" }), h("i", { class: "hatch", style: "width:30%" })),
    h("p", { class: "msub", text: "34 correct · 12 wrong · 19 not attempted" }),
    h("p", { class: "mnote", text: "Weakest topic: Operating System › deadlock. You lost 5 of 8 marks there." }));

  const features = h("div", { class: "lfeats" },
    row(false, "Build", "Build the test you need", "Type a topic like “deadlock” or “b+ tree”, pick a whole subject, or take a full mock. Questions you have already seen are skipped first.", buildMock),
    row(true, "Analyse", "Know where your marks went", "Every result shows marks lost to negative marking, topics ranked by marks lost, time against the real pace, and what to practise next.", analysisMock));

  const faq = h("section", { class: "lfaq", id: "faq" },
    h("div", { class: "stack" }, eyebrow("FAQ"), h("h2", { class: "ltitle", text: "Questions, answered" }), h("p", { class: "lead", text: "Short, honest answers about how aceIt works." })),
    h("div", { class: "lfaq-list" }, FAQ.map(([q, a], i) => h("details", { class: "qa", open: i === 0 }, h("summary", { text: q }), h("p", { text: a })))));

  const final = h("section", { class: "lfinal", id: "start" },
    h("div", { class: "stack" }, eyebrow("Your next step"), h("h2", { class: "hero small", text: "Start practising today" }),
      h("p", { class: "lead", text: "Create an account with your email and take your first test in under a minute." }), cta("Start for free")));

  const foot = h("footer", { class: "lfoot" }, h("span", { class: "logo" }, h("i"), "aceIt"),
    h("span", { class: "sub", text: "aceIt is an independent practice site. It is not affiliated with GATE or the institutes that organise it." }));

  clear(app).append(h("div", { class: "wrap land", id: "main" }, nav, hero, strip, about, features, faq, final, foot));
}
