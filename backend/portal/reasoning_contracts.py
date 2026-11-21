"""Allowlisted Chat Completions payload fragments. No metadata-defined JSON paths."""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Contract:
    controls: tuple[str, ...]
    encode: Callable[[dict], dict]
    exclusive: tuple[str, ...] = ()


def effort(values):
    return {"reasoning_effort": values["effort"]} if "effort" in values else {}


def thinking(values):
    if values.get("toggle") is False:
        return {"thinking": {"type": "disabled"}}
    result = effort(values)
    if values:
        result["thinking"] = {"type": "enabled"}
        if "budget" in values:
            result["thinking"]["budget_tokens"] = values["budget"]
    return result


def router(values):
    names = {"toggle": "enabled", "effort": "effort", "budget": "max_tokens"}
    return {"reasoning": {names[k]: v for k, v in values.items()}} if values else {}


def kimi(values):
    if "effort" in values:
        return {
            "thinking": {"type": "enabled", "effort": values["effort"], "keep": "all"}
        }
    return {}


WIRE = {
    "none": Contract((), lambda _: {}),
    "always": Contract((), lambda _: {}),
    "native_effort": Contract(("effort",), effort),
    "effort": Contract(("effort",), effort),
    "toggle": Contract(("toggle",), thinking),
    "toggle_effort": Contract(("toggle", "effort"), thinking),
    "budget_tokens": Contract(("budget",), thinking),
    "thinking_controls": Contract(("toggle", "effort", "budget"), thinking),
    "router_effort": Contract(
        ("toggle", "effort", "budget"), router, ("effort", "budget")
    ),
    "kimi_preserved": Contract(("effort",), kimi),
}


def scalar_values(wire, level, budgets):
    """Translate a historical scalar strictly according to its original wire dialect."""
    if not level or wire in ("always", "none"):
        return {}
    if wire == "budget_tokens":
        if level not in budgets:
            from django.core.exceptions import ValidationError

            raise ValidationError("برای این سطح بودجهٔ معتبر ثبت نشده است.")
        return {"budget": budgets[level]}
    if wire == "toggle" or (wire == "toggle_effort" and level == "off"):
        return {"toggle": level != "off"}
    return {"effort": level}
