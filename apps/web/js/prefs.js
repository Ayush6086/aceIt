// Display preference: theme (follow the device, light or dark). Stored in this browser only.
const KEY = "aceit.prefs";
const THEMES = ["auto", "light", "dark"];
const LABEL = { auto: "Auto", light: "Light", dark: "Dark" };

let prefs = { theme: "auto" };
try { prefs = { ...prefs, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { /* private window: defaults */ }
if (!THEMES.includes(prefs.theme)) prefs.theme = "auto";

export function applyPrefs() {
  const r = document.documentElement;
  prefs.theme === "auto" ? r.removeAttribute("data-theme") : r.setAttribute("data-theme", prefs.theme);
  r.removeAttribute("data-size");                      // the old text-size setting is gone
}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* not saved, still applied */ } };
export const next = (list, v) => list[(list.indexOf(v) + 1) % list.length];
export const cycle = () => { prefs.theme = next(THEMES, prefs.theme); save(); applyPrefs(); return prefs.theme; };

/** One small button that cycles the theme. `h` is the DOM helper. */
export function prefsButtons(h) {
  const t = h("button", { class: "pill", type: "button", title: "Colour theme: auto, light or dark" }, `◐ ${LABEL[prefs.theme]}`);
  t.onclick = () => { t.textContent = `◐ ${LABEL[cycle()]}`; };
  return h("span", { class: "prefs", role: "group", "aria-label": "Display settings" }, t);
}
