import test from "node:test";
import assert from "node:assert/strict";
import { splitMath, hasMath } from "../js/math.js";

test("inline and display maths are separated from plain text", () => {
  assert.deepEqual(splitMath("so $x^2$ and $$\\frac{a}{b}$$ done"), [{ text: "so " }, { tex: "x^2", display: false }, { text: " and " }, { tex: "\\frac{a}{b}", display: true }, { text: " done" }]);
  assert.deepEqual(splitMath("no maths here"), [{ text: "no maths here" }]);
  assert.deepEqual(splitMath(""), []);
});

test("money and stray dollar signs are not maths", () => {
  assert.equal(hasMath("It costs $5 and $6 in total"), false);          // closing dollar follows a space / digit follows
  assert.equal(hasMath("a lone $ sign"), false);
  assert.equal(hasMath("price is \\$5 or \\$7"), false);                 // escaped dollars stay text
  assert.deepEqual(splitMath("pay \\$5 for $y$"), [{ text: "pay $5 for " }, { tex: "y", display: false }]);
});

test("a formula needs no space just inside the dollars", () => {
  assert.equal(hasMath("$ x $"), false);
  assert.equal(hasMath("$x$"), true);
  assert.equal(hasMath("$2^{10} = 1024$ bytes"), true);
});
