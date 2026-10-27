import { api, session } from "./api.js";
import * as auth from "./auth.js";
import { applyPrefs, prefsButtons } from "./prefs.js";
applyPrefs();
import { h, clear } from "./dom.js";
import { homeView } from "./home.js";
import { examView, leaveExam } from "./exam.js";
import { resultView } from "./result.js";
import { landingView } from "./landing.js";

const app = document.getElementById("app");

export function header(user) {
  return h("header", { class: "top" },
    h("a", { class: "logo", href: "#/", "aria-label": "aceIt home" }, h("i"), "aceIt"),
    h("span", { class: "grow" }),
    prefsButtons(h),
    user && session.username ? h("span", { class: "sub" }, session.username) : null,
    user ? h("button", { class: "pill", onclick: () => { const c = session.cognito && auth.tokens.get() ? session.cognito : null; session.clear(); c ? auth.signOut(c) : (location.hash = "#/", route()); } }, "Sign out") : null);
}

let flash = null;                                      // a one-time message for the login page (e.g. a failed sign-in)

async function loginView() {
  document.body.classList.remove("exam");
  let cfg = { auth_mode: "dev" };
  try { cfg = await api("/config"); } catch { /* show the form anyway */ }
  const startCognito = () => auth.startLogin(cfg.cognito).catch((e) => { err.hidden = false; err.textContent = e.message; });
  const err = h("p", { class: "notice err", role: "alert", hidden: !flash }, flash || "");
  flash = null;
  const input = h("input", { type: "text", id: "who", placeholder: "Your name", "aria-label": "Your name", autocomplete: "off", maxlength: "40" });
  const go = () => {
    const n = input.value.trim().toLowerCase().replace(/[^a-z0-9._-]/g, "");
    if (!n) { err.hidden = false; err.textContent = "Enter a name to continue."; return; }
    session.set(n); location.hash = "#/";
  };
  input.addEventListener("keydown", (e) => e.key === "Enter" && go());
  clear(app).append(h("div", { class: "wrap", id: "main" }, header(null),
    h("div", { class: "grid" },
      h("section", { class: "card lime span-7" }, h("div", { class: "stack" },
        h("div", { class: "label", text: "GATE CS · free mock tests" }),
        h("h1", { class: "hero", text: "Practice like it's the real GATE." }),
        h("p", { text: "Timed CS mock tests built from past papers, with a clear picture of where your marks go." }),
        cfg.auth_mode === "dev"
          ? h("div", { class: "stack" }, h("p", { class: "notice" }, "Development sign-in: no password. Pick any name."), h("div", { class: "row" }, input, h("button", { class: "btn go", onclick: go }, "Continue")), err)
          : cfg.cognito
            ? h("div", { class: "stack" }, h("div", { class: "row" }, h("button", { class: "btn go", onclick: startCognito }, "Sign in or create an account")), err,
                h("p", { class: "sub", text: "You will sign in on a secure page with your email. We never see your password." }),
                h("p", { class: "sub", text: "New here? Choose a password of at least 10 characters with an upper-case letter, a lower-case letter and a number. We email you a code to confirm your address." }))
            : h("p", { class: "notice" }, "Sign-in with your account is not set up in this environment yet."))),
      h("section", { class: "card black span-5" }, h("div", { class: "label", text: "The real shape" }),
        h("div", { class: "stats3" }, [["65", "questions"], ["100", "marks"], ["3", "hours"]].map(([n, l]) => h("div", {}, h("div", { class: "big", text: n }), h("div", { class: "sub", text: l })))),
        h("p", { class: "sub", style: "margin-top:22px", text: "Negative marking, numerical answers and multi-select questions, scored against the official answer keys." })))));
  input.focus?.();
}

/** First sign-in: the student picks the name shown in the app, so their email is never displayed. */
function usernameView() {
  document.body.classList.remove("exam");
  const err = h("p", { class: "notice err", role: "alert", hidden: true });
  const input = h("input", { type: "text", id: "uname", placeholder: "Username", "aria-label": "Username", autocomplete: "off", maxlength: "20" });
  const save = async () => {
    const u = input.value.trim();
    if (!/^[A-Za-z0-9_]{3,20}$/.test(u)) { err.hidden = false; err.textContent = "Use 3 to 20 letters, numbers or underscores."; return; }
    try { await api("/me/username", { method: "PUT", body: { username: u } }); session.username = u; route(); }
    catch (e) { err.hidden = false; err.textContent = e.message; }
  };
  input.addEventListener("keydown", (e) => e.key === "Enter" && save());
  clear(app).append(h("div", { class: "wrap", id: "main" }, header(session.user),
    h("section", { class: "card lime" }, h("div", { class: "stack" }, h("div", { class: "label", text: "Welcome" }), h("h1", { class: "hero", text: "Pick a username" }),
      h("div", { class: "row" }, input, h("button", { class: "btn go", onclick: save }, "Continue")), err))));
  input.focus();
}

async function route() {
  const hash = location.hash || "#/";
  leaveExam();
  if (!(session.user || session._mem) && hash !== "#/login") return landingView(app, session.cognito);      // signed out: the front door
  try {
    const [, page, id] = hash.split("/");
    if (hash === "#/login") return await loginView();
    if (session.username === undefined) session.username = (await api("/me")).username;
    if (!session.username) return usernameView();
    if (page === "exam" && id) return await examView(app, id);
    document.body.classList.remove("exam");
    if (page === "result" && id) return await resultView(app, id);
    return await homeView(app);
  } catch (e) {
    document.body.classList.remove("exam");
    if (e.status === 401) return;
    clear(app).append(h("div", { class: "wrap", id: "main" }, header(session.user), h("p", { class: "notice err", role: "alert" }, `${e.message || "Something went wrong."} (page: ${hash.split("/")[1] || "home"})`), h("a", { class: "btn", href: "#/" }, "Back to home")));
  }
}

addEventListener("hashchange", route);

// Start-up: learn how to sign in, and if Cognito just sent the browser back with a code, finish signing in first.
(async () => {
  try { session.cognito = (await api("/config")).cognito; } catch { /* offline: the login screen reports it */ }
  if (session.cognito) {
    try { await auth.handleCallback(session.cognito); }
    catch (e) { flash = e.message; if (location.hash === "#/login") route(); else location.hash = "#/login"; return; }
  }
  route();
})();
