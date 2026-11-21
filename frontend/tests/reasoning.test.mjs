import assert from "node:assert/strict";
import test from "node:test";
import { ready, selectionFor } from "../src/reasoning.ts";

const profile = (...controls) => ({ available: true, controls, exclusive: [] });
const effort = {
  type: "effort",
  options: [{ value: "none" }, { value: "custom.depth" }],
  default: "none",
  default_source: "provider",
};
test("untouched optional provider defaults stay implicit and raw custom values survive", () => {
  assert.deepEqual(selectionFor(profile(effort)), {});
  assert.deepEqual(selectionFor(profile(effort), { effort: "custom.depth" }), {
    effort: "custom.depth",
  });
  assert.deepEqual(
    selectionFor(profile({ ...effort, default_source: "manual" })),
    { effort: "none" },
  );
  assert.deepEqual(selectionFor(profile(effort), { effort: "old" }), {});
});
test("disabled combined reasoning has no effort or budget, required effort is scoped to enabled runs", () => {
  const p = profile(
    { type: "toggle", options: [{ value: true }, { value: false }] },
    { ...effort, required: true },
  );
  const saved = { toggle: false, effort: "custom.depth" };
  assert.deepEqual(selectionFor(p, saved), { toggle: false });
  assert.ok(ready(p, saved));
  assert.equal(ready(p, { toggle: true }), false);
  assert.deepEqual(saved, { toggle: false, effort: "custom.depth" });
});
test("budget presets and ranges reject out-of-bounds or unlisted values", () => {
  const range = { type: "budget", min: 32, max: 256 };
  assert.ok(ready(profile(range), { budget: 200 }));
  assert.equal(ready(profile(range), { budget: 257 }), false);
  assert.equal(
    ready(profile({ ...range, options: [{ value: 32 }, { value: 256 }] }), {
      budget: 200,
    }),
    false,
  );
  assert.equal(ready({ ...profile(), available: false }), false);
});
