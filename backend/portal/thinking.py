"""Validated wire contracts. A model opts in to a subset through Django Admin."""

from django.core.exceptions import ValidationError

LEVELS = ("off", "on", "low", "high", "max")
CONTRACTS = {
    "none": (),
    "always": ("on",),
    "toggle": ("off", "on"),
    "effort": ("low", "high", "max"),
    "toggle_effort": ("off", "low", "high", "max"),
    "kimi_preserved": ("low", "high", "max"),
}
POLICIES = [
    ("hidden", "عدم نمایش و ذخیره"),
    ("live", "فقط نمایش زنده"),
    ("store", "نمایش و ذخیره"),
    ("preserve", "نمایش، ذخیره و ارسال در تاریخچهٔ همین مدل"),
]


def validate_capabilities(model):
    if model.output_parameter not in ("max_tokens", "max_completion_tokens"):
        raise ValidationError({"output_parameter": "نام پارامتر خروجی نامعتبر است."})
    allowed = CONTRACTS.get(model.thinking_contract)
    levels = model.thinking_levels
    if (
        allowed is None
        or not isinstance(levels, list)
        or any(level not in allowed for level in levels)
        or len(levels) != len(set(levels))
        or bool(levels) != bool(allowed)
        or (levels and model.thinking_default not in levels)
        or (not levels and model.thinking_default)
        or (model.provider == "demo" and levels)
    ):
        raise ValidationError(
            {"thinking_levels": "سطح‌ها و پیش‌فرض باید با قرارداد مدل سازگار باشند."}
        )
    if (
        model.thinking_contract == "kimi_preserved"
        and model.reasoning_policy != "preserve"
    ):
        raise ValidationError(
            {
                "reasoning_policy": "این قرارداد Kimi به نگه‌داری تاریخچهٔ استدلال نیاز دارد."
            }
        )
    if model.reasoning_policy not in dict(POLICIES) or (
        not levels and model.reasoning_policy != "hidden"
    ):
        raise ValidationError(
            {"reasoning_policy": "سیاست استدلال با قابلیت مدل سازگار نیست."}
        )
    if (
        model.provider_output_limit is not None
        and model.max_output_tokens > model.provider_output_limit
    ):
        raise ValidationError(
            {"max_output_tokens": "بودجه از سقف مستند سرویس بیشتر است."}
        )


def parameters(contract, level):
    if not level or contract == "always":
        return {}
    if contract == "kimi_preserved":
        return {"thinking": {"type": "enabled", "effort": level, "keep": "all"}}
    payload = {}
    if contract in ("toggle", "toggle_effort"):
        payload["thinking"] = {"type": "disabled" if level == "off" else "enabled"}
    if contract in ("effort", "toggle_effort") and level != "off":
        payload["reasoning_effort"] = level
    return payload
