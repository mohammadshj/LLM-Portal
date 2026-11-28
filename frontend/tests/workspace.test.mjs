import test from "node:test";
import assert from "node:assert/strict";
import {
  historyGroups,
  readPreferences,
  remember,
} from "../src/preferences.ts";
test("pins appear once, ahead of local calendar day groups", () => {
  const now = new Date(2026, 10, 28, 0, 10);
  const rows = [0, 1, 3, 10, 32, 7].map((age, i) => ({
    id: i,
    created_at: new Date(2026, 10, 28 - age).toISOString(),
    pinned: i === 5,
  }));
  assert.deepEqual(
    historyGroups(rows, now).map(([key, items]) => [
      key,
      items.map((i) => i.id),
    ]),
    [
      ["سنجاق‌شده", [5]],
      ["امروز", [0]],
      ["دیروز", [1]],
      ["۷ روز گذشته", [2]],
      ["۳۰ روز گذشته", [3]],
      ["قدیمی‌تر", [4]],
    ],
  );
});
test("model preferences are scoped per user and recover from invalid saved data", () => {
  const items = new Map();
  globalThis.localStorage = {
    getItem: (k) => items.get(k),
    setItem: (k, v) => items.set(k, v),
  };
  try {
    remember("a", {
      chat: [1],
      compare: [2, 3],
      recent: [3, 2],
      collapsed: true,
    });
    assert.deepEqual(readPreferences("a").compare, [2, 3]);
    assert.deepEqual(readPreferences("b").recent, []);
    items.set("portal-workspace:a", "null");
    assert.equal(readPreferences("a").collapsed, false);
  } finally {
    delete globalThis.localStorage;
  }
});
