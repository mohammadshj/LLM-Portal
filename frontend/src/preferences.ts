import type { Conversation, Model } from "./types";
export type Mode = "chat" | "compare";
export type Preferences = {
  chat: number[];
  compare: number[];
  recent: number[];
  collapsed: boolean;
};
export function readPreferences(user: string): Preferences {
  let raw;
  try {
    raw = JSON.parse(localStorage.getItem("portal-workspace:" + user) || "{}");
  } catch {
    /* session defaults */
  }
  const ids = (v: unknown) =>
    Array.isArray(v)
      ? [...new Set(v.filter((n): n is number => Number.isInteger(n) && n > 0))]
      : [];
  return {
    chat: ids(raw?.chat).slice(0, 1),
    compare: ids(raw?.compare).slice(0, 3),
    recent: ids(raw?.recent).slice(0, 6),
    collapsed: raw?.collapsed === true,
  };
}
export function remember(user: string, prefs: Preferences) {
  try {
    localStorage.setItem("portal-workspace:" + user, JSON.stringify(prefs));
  } catch {
    /* current session remains usable */
  }
}
export function available(m: Model) {
  return (
    m.available !== false &&
    m.input_price_per_million_rial != null &&
    m.output_price_per_million_rial != null
  );
}
export function historyGroups(rows: Conversation[], now = new Date()) {
  const day = (d: Date) =>
    Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 86400000;
  const groups = new Map(
    [
      "سنجاق‌شده",
      "امروز",
      "دیروز",
      "۷ روز گذشته",
      "۳۰ روز گذشته",
      "قدیمی‌تر",
    ].map((k) => [k, [] as Conversation[]]),
  );
  for (const row of rows) {
    const age = row.created_at
      ? day(now) - day(new Date(row.created_at))
      : Infinity;
    const name = row.pinned
      ? "سنجاق‌شده"
      : age <= 0
        ? "امروز"
        : age === 1
          ? "دیروز"
          : age < 7
            ? "۷ روز گذشته"
            : age < 30
              ? "۳۰ روز گذشته"
              : "قدیمی‌تر";
    groups.get(name)!.push(row);
  }
  return [...groups].filter(([, items]) => items.length);
}
