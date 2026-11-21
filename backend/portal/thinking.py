"""Validated wire contracts. A model opts in to a subset through Django Admin."""

import re

from django.core.exceptions import ValidationError


def valid_level(value):
    return (
        isinstance(value, str)
        and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,31}", value) is not None
    )


CONTRACTS = {
    "native_effort": None,
    "router_effort": None,
    "budget_tokens": None,
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
        model.thinking_contract not in CONTRACTS
        or not isinstance(levels, list)
        or len(levels) > 64
        or any(
            not valid_level(level) or (allowed is not None and level not in allowed)
            for level in levels
        )
        or len(levels) != len(set(levels))
        or bool(levels) != (model.thinking_contract != "none")
        or (levels and allowed is not None and not model.thinking_default)
        or (model.thinking_default and model.thinking_default not in levels)
        or (model.provider == "demo" and levels)
    ):
        raise ValidationError(
            {"thinking_levels": "سطح‌ها و پیش‌فرض باید با قرارداد مدل سازگار باشند."}
        )
    if model.thinking_contract == "budget_tokens":
        budgets = model.thinking_budgets
        if (
            not isinstance(budgets, dict)
            or set(budgets) != set(levels)
            or any(
                type(n) is not int or n < 1 or n >= model.max_output_tokens
                for n in budgets.values()
            )
        ):
            raise ValidationError(
                {
                    "thinking_budgets": "هر سطح به بودجهٔ صحیح مثبت و کمتر از سقف خروجی نیاز دارد."
                }
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
        not levels
        and not model.auto_thinking
        and not model.reasoning_overrides
        and model.reasoning_policy != "hidden"
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


def parameters(contract, level, budgets=None):
    """Compatibility API for callers with an already validated scalar level."""
    from .reasoning_contracts import WIRE, scalar_values

    return WIRE[contract].encode(scalar_values(contract, level, budgets or {}))
