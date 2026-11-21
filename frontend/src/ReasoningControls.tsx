import type { Model, ReasoningSettings } from "./types";
import { selectionFor } from "./reasoning";
import { number } from "./ui";

const names: Record<string, string> = {
  minimal: "حداقلی",
  low: "کم",
  medium: "متوسط",
  high: "زیاد",
  maximum: "بیشینه",
  disabled: "خاموش",
};
export function ReasoningControls({
  model,
  saved,
  change,
}: {
  model: Model;
  saved?: ReasoningSettings;
  change: (v: ReasoningSettings) => void;
}) {
  const profile = model.reasoning_profile;
  const values = selectionFor(profile, saved);
  function update(
    kind: keyof ReasoningSettings,
    value?: number | string | boolean,
  ) {
    const next = { ...values };
    delete next[kind];
    if (value !== undefined) {
      for (const other of profile.exclusive)
        if (kind !== other && profile.exclusive.includes(kind))
          delete next[other];
      Object.assign(next, { [kind]: value });
    }
    const disabledOption = profile.controls
      .find((c) => c.type === "effort")
      ?.options?.find((o) => o.disables_reasoning && o.value === next.effort);
    if (disabledOption && next.toggle === true) {
      if (kind === "toggle") delete next.effort;
      else delete next.toggle;
    }
    change(next.toggle === false ? { toggle: false } : next);
  }
  return (
    <fieldset className="reasoning-controls">
      <legend>
        <bdi>{model.name}</bdi>
      </legend>
      {profile.mandatory && <small>استدلال برای این مدل اجباری است.</small>}
      {profile.controls.map((c) => {
        const name =
          (c.type === "toggle"
            ? "فعال‌سازی استدلال"
            : c.type === "budget"
              ? "بودجهٔ استدلال"
              : "شدت استدلال") +
          " " +
          model.name;
        if (c.type === "toggle")
          return (
            <div key={c.type} className="setting">
              <label>
                <input
                  type="checkbox"
                  role="switch"
                  aria-label={name}
                  checked={values.toggle === true}
                  disabled={c.options?.length === 1}
                  onChange={(e) => update("toggle", e.target.checked)}
                />{" "}
                استدلال
              </label>
              <small>
                {values.toggle == null
                  ? "پیش‌فرض سرویس"
                  : values.toggle
                    ? "روشن"
                    : "خاموش"}
              </small>
              {!c.required && values.toggle != null && (
                <button type="button" onClick={() => update("toggle")}>
                  پیش‌فرض سرویس
                </button>
              )}
            </div>
          );
        if (values.toggle === false) return null;
        if (c.type === "budget" && !c.options?.length)
          return (
            <div className="setting budget-range" key="budget">
              <label>
                {name}
                <input
                  type="range"
                  aria-label={name}
                  min={c.min}
                  max={c.max}
                  step={1}
                  value={values.budget ?? c.min}
                  onChange={(e) => update("budget", e.target.valueAsNumber)}
                />
              </label>
              <label>
                تعداد دقیق توکن
                <input
                  type="number"
                  aria-label={"تعداد توکن استدلال " + model.name}
                  min={c.min}
                  max={c.max}
                  step={1}
                  placeholder={c.required ? "الزامی" : "پیش‌فرض سرویس"}
                  value={saved?.budget ?? values.budget ?? ""}
                  onChange={(e) =>
                    update(
                      "budget",
                      e.target.value === ""
                        ? undefined
                        : e.target.valueAsNumber,
                    )
                  }
                />
              </label>
              <small>
                {number(c.min!)} تا {number(c.max!)} توکن
              </small>
            </div>
          );
        return (
          <label className="setting" key={c.type}>
            {c.type === "budget" ? "بودجهٔ استدلال (توکن)" : "شدت استدلال"}
            <select
              aria-label={name}
              value={values[c.type] ?? ""}
              onChange={(e) =>
                update(
                  c.type,
                  !e.target.value
                    ? undefined
                    : c.type === "budget"
                      ? Number(e.target.value)
                      : e.target.value,
                )
              }
            >
              <option value="" disabled={c.required}>
                {c.required
                  ? "انتخاب کنید"
                  : c.default != null
                    ? "پیش‌فرض سرویس (" + c.default + ")"
                    : "پیش‌فرض سرویس"}
              </option>
              {c.options?.map((o) => (
                <option key={String(o.value)} value={String(o.value)}>
                  {o.label ||
                    names[o.semantic_level ?? "unknown"] ||
                    (typeof o.value === "number"
                      ? number(o.value)
                      : String(o.value))}
                </option>
              ))}
            </select>
          </label>
        );
      })}
    </fieldset>
  );
}
