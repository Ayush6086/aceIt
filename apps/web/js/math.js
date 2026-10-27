// Formatted maths for explanations: $inline$ and $$display$$ LaTeX rendered with KaTeX (vendored in vendor/katex, loaded only when
// a text actually contains maths). Everything outside the maths stays plain text, so no HTML can be injected through it.
const MATH = /\$\$([^$]+?)\$\$|(?<![\\$])\$(?!\s)([^$\n]*?[^\s\\$])\$(?!\d)/g;     // $$..$$ or $..$ (no space inside the dollars, not followed by a digit, so "$5 and $6" is money)

/** Split text into plain and maths parts: [{text}, {tex, display}, ...]. Pure, so it is easy to test. */
export function splitMath(text) {
  const out = []; let last = 0;
  for (const m of String(text ?? "").matchAll(MATH)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index) });
    out.push({ tex: (m[1] ?? m[2]).trim(), display: m[1] !== undefined });
    last = m.index + m[0].length;
  }
  if (last < String(text ?? "").length) out.push({ text: text.slice(last) });
  return out.map((p) => (p.text !== undefined ? { text: p.text.replaceAll("\\$", "$") } : p));      // \$ is a literal dollar sign
}
export const hasMath = (text) => splitMath(text).some((p) => p.tex !== undefined);

let katex = null;
async function load() {
  if (katex) return katex;
  if (!document.getElementById("katex-css")) {
    const l = document.createElement("link"); l.id = "katex-css"; l.rel = "stylesheet"; l.href = "vendor/katex/katex.min.css"; document.head.append(l);
  }
  katex = await import("../vendor/katex/katex.mjs").then((m) => m.default ?? m);
  return katex;
}

/** A DOM node showing `text` with its maths typeset. If KaTeX cannot load, the raw text is shown instead. */
export async function mathNode(text, tag = "p", cls = "") {
  const el = document.createElement(tag); if (cls) el.className = cls;
  const parts = splitMath(text);
  if (!parts.some((p) => p.tex !== undefined)) { el.textContent = text; return el; }
  let k; try { k = await load(); } catch { el.textContent = text; return el; }
  for (const p of parts) {
    if (p.text !== undefined) { el.append(document.createTextNode(p.text)); continue; }
    const span = document.createElement("span");
    try { span.innerHTML = k.renderToString(p.tex, { displayMode: p.display, throwOnError: false, trust: false, strict: "ignore", output: "htmlAndMathml" }); }
    catch { span.textContent = p.display ? `$$${p.tex}$$` : `$${p.tex}$`; }
    if (p.display) span.className = "math-display";
    el.append(span);
  }
  return el;
}
