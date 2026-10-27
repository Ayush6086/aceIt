import test from "node:test";
import assert from "node:assert/strict";
import { next, cycle } from "../js/prefs.js";

test("preferences cycle through their options and wrap around", () => {
  assert.equal(next(["auto", "light", "dark"], "auto"), "light");
  assert.equal(next(["auto", "light", "dark"], "dark"), "auto");
  assert.equal(next(["normal", "large", "xlarge"], "large"), "xlarge");
  assert.equal(next(["a", "b"], "unknown"), "a");                  // an unknown value restarts the cycle
});

test("importing the module works with no browser storage (private window)", () => {
  assert.equal(typeof cycle, "function");
});
