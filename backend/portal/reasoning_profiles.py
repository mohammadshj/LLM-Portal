"""Resolve UI controls independently of wire spelling and validate typed selections."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError

from .reasoning_contracts import WIRE, scalar_values


@dataclass
class ReasoningCapabilityProfile:
    supported: bool | None
    mandatory: bool | None
    wire: str
    controls: list
    fixed: bool = False
    unavailable_required: bool = False

    def public(self):
        kinds = [c["type"] for c in self.controls]
        if kinds:
            mode = kinds[0] if len(kinds) == 1 else "combined"
        elif self.fixed:
            mode = "fixed"
        else:
            mode = "none" if self.supported is False else "unknown"
        return dict(
            supported=self.supported,
            mandatory=self.mandatory,
            mode=mode,
            controls=self.controls,
            available=not self.unavailable_required,
            exclusive=list(WIRE[self.wire].exclusive),
        )

    def defaults(self):
        return {
            c["type"]: c["default"]
            for c in self.controls
            if c.get("default") is not None
        }

    def payload(self, values):
        invalid = ValidationError("تنظیم استدلال با گزینه‌های مجاز این مدل سازگار نیست.")
        if self.unavailable_required:
            raise ValidationError(
                "سطح استدلال الزامی است اما گزینهٔ معتبری برای این مدل ثبت نشده است."
            )
        if not isinstance(values, dict) or set(values) - {
            c["type"] for c in self.controls
        }:
            raise invalid
        if values.get("toggle") is False and len(values) != 1:
            raise invalid
        if len(set(WIRE[self.wire].exclusive).intersection(values)) > 1:
            raise invalid
        for c in self.controls:
            kind = c["type"]
            if kind not in values:
                if c["required"] and values.get("toggle") is not False:
                    raise invalid
                continue
            v = values[kind]
            if type(v) is not {"toggle": bool, "effort": str, "budget": int}[kind]:
                raise invalid
            if c.get("options") and v not in [opt["value"] for opt in c["options"]]:
                raise invalid
            if (
                kind == "effort"
                and values.get("toggle") is True
                and any(
                    o["value"] == v and o.get("disables_reasoning")
                    for o in c["options"]
                )
            ):
                raise invalid
            if kind == "budget" and not c["min"] <= v <= c["max"]:
                raise invalid
        return WIRE[self.wire].encode(values)


def option(value, labels, semantics):
    return {
        "value": value,
        "label": labels.get(value, ""),
        "semantic_level": semantics.get(value, "unknown"),
    }


def build_profile(model, facts, sources):
    supported = facts.get("reasoning")
    mandatory = facts.get("reasoning_mandatory")
    wire = facts.get("wire")
    if model.provider == "demo" or supported is False:
        return ReasoningCapabilityProfile(False, None, "none", [])
    if supported is not True or wire not in WIRE:
        return ReasoningCapabilityProfile(
            supported,
            mandatory,
            "none",
            [],
            unavailable_required=any(
                facts.get(k + "_required") is True
                for k in ("effort", "toggle", "budget")
            ),
        )
    contract = WIRE[wire]
    controls = []
    for kind in contract.controls:
        control = {"type": kind, "required": facts.get(kind + "_required") is True}
        if kind == "toggle":
            if mandatory or facts.get("reasoning_toggle") is not True:
                continue
            control["options"] = [
                {"value": v} for v in facts.get("toggle_values", [False, True])
            ]
            default = facts.get("default_enabled")
        elif kind == "effort":
            options = facts.get("efforts", [])
            disabled = set(facts.get("disabled_efforts", []))
            if wire == "router_effort":
                disabled.add("none")
            if mandatory:
                options = [v for v in options if v not in disabled]
            if not options:
                continue
            control["options"] = [
                {
                    **option(
                        v,
                        facts.get("effort_labels", {}),
                        facts.get("effort_semantics", {}),
                    ),
                    "disables_reasoning": v in disabled,
                }
                for v in options
            ]
            default = facts.get("default_effort")
            if wire == "router_effort" and (
                facts.get("default_enabled") is not True or default == "none"
            ):
                default = None
        else:
            if (
                wire == "router_effort"
                and facts.get("router_budget_supported") is False
            ):
                continue
            limits = facts.get("budget_tokens", {})
            presets = facts.get("budget_presets", [])
            lo, hi = limits.get("min"), limits.get("max")
            if presets:
                lo = min(presets) if lo is None else lo
                hi = max(presets) if hi is None else hi
            if type(lo) is not int or type(hi) is not int or lo < 1 or hi < lo:
                continue
            hi = min(hi, model.max_output_tokens - 1)
            valid = [v for v in presets if lo <= v <= hi]
            if hi < lo or (presets and not valid):
                continue
            control.update(min=lo, max=hi, options=[{"value": v} for v in valid])
            default = facts.get("default_budget")
            if default is not None and not lo <= default <= hi:
                default = None
        options = control.get("options", [])
        if default is not None and (
            not options or default in [o["value"] for o in options]
        ):
            control["default"] = default
            source_key = {
                "toggle": "default_enabled",
                "effort": "default_effort",
                "budget": "default_budget",
            }[kind]
            control["default_source"] = sources.get(source_key, "unknown")
        controls.append(control)
    if facts.get("default_enabled") is False:
        for c in controls:
            if c["type"] != "toggle":
                c.pop("default", None)
    if wire == "always":
        mandatory = True
    mutually_exclusive_defaults = [
        c for c in controls if c["type"] in contract.exclusive and "default" in c
    ]
    if len(mutually_exclusive_defaults) > 1:
        for c in mutually_exclusive_defaults:
            del c["default"]
    missing = any(
        facts.get(k + "_required") and not any(c["type"] == k for c in controls)
        for k in ("budget", "effort", "toggle")
    )
    return ReasoningCapabilityProfile(
        True, mandatory, wire, controls, wire == "always", missing
    )


def legacy_selection(model, level):
    if level == "":
        return {}
    if level not in model.thinking_levels:
        raise ValidationError("سطح استدلال برای این مدل مجاز نیست.")
    if model.auto_thinking or model.reasoning_profile.wire != model.thinking_contract:
        return {"effort": level}
    return scalar_values(model.reasoning_profile.wire, level, model.thinking_budgets)
