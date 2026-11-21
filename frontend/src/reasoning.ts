import type { ReasoningProfile, ReasoningSettings } from "./types";

export function selectionFor(
  profile: ReasoningProfile,
  saved?: ReasoningSettings,
): ReasoningSettings {
  const values: ReasoningSettings = {};
  for (const control of profile.controls) {
    const value =
      saved === undefined
        ? control.default_source === "manual" || control.required
          ? control.default
          : undefined
        : saved[control.type];
    if (value == null) continue;
    if (
      control.options?.length &&
      !control.options.some((o) => o.value === value)
    )
      continue;
    if (
      control.type === "budget" &&
      (typeof value !== "number" ||
        !Number.isInteger(value) ||
        value < control.min! ||
        value > control.max!)
    )
      continue;
    Object.assign(values, { [control.type]: value });
  }
  return values.toggle === false ? { toggle: false } : values;
}

export function ready(profile: ReasoningProfile, saved?: ReasoningSettings) {
  const values = selectionFor(profile, saved);
  if (!profile.available) return false;
  if (
    saved?.budget != null &&
    values.toggle !== false &&
    profile.controls.some((c) => c.type === "budget") &&
    values.budget == null
  )
    return false;
  return (
    values.toggle === false ||
    profile.controls.every((c) => !c.required || values[c.type] != null)
  );
}
