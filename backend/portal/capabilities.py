"""Resolve connection-scoped evidence and operator overrides into a runtime model."""

from copy import copy
from hashlib import sha256

from django.core.exceptions import ValidationError

from .catalog_metadata import FLAGS, LIMITS, levels, positive, valid_effort
from .reasoning_contracts import WIRE, scalar_values
from .reasoning_profiles import build_profile
from .thinking import valid_level


def validate_overrides(value):
    if not isinstance(value, dict) or any(
        not (key in FLAGS and type(v) is bool or key in LIMITS and positive(v))
        for key, v in value.items()
    ):
        raise ValidationError(
            "قابلیت دستی باید مقدار بولی یا سقف عددی مثبت و کلید معتبر داشته باشد."
        )


def connection_signature(conn):
    return sha256(
        repr(
            (
                conn.pk,
                conn.base_url.rstrip("/"),
                conn.api_key_env,
                conn.discovery_type,
                conn.registry_provider,
            )
        ).encode()
    ).hexdigest()


def current_catalog(model):
    data = model.discovery_data
    if data and (
        data.get("model_id") != model.model_id
        or not model.connection_id
        or data.get("connection") != connection_signature(model.connection)
    ):
        return {}
    return data


def legacy_facts(model):
    """Interpret old values only inside their original, explicitly configured contract."""
    legacy = model.thinking_contract
    lv = model.thinking_levels
    default = model.thinking_default
    extra = {
        "wire": legacy,
        "reasoning": True,
        "efforts": lv,
        "default_effort": default,
    }
    if legacy in ("always", "kimi_preserved"):
        extra["reasoning_mandatory"] = True
    if legacy in ("effort", "kimi_preserved"):
        extra["effort_required"] = True
    if legacy in ("toggle", "toggle_effort"):
        extra.update(
            reasoning_toggle=legacy == "toggle" or "off" in lv,
            reasoning_mandatory=False if "off" in lv else None,
            efforts=[x for x in lv if x not in ("on", "off")],
            toggle_values=[
                v
                for v, available in [
                    (False, "off" in lv),
                    (True, any(x != "off" for x in lv)),
                ]
                if available
            ],
        )
        if default:
            extra["default_enabled"] = default != "off"
        if legacy == "toggle_effort":
            extra["effort_required"] = bool(extra["efforts"])
    if legacy == "budget_tokens":
        extra.update(
            budget_presets=list(model.thinking_budgets.values()),
            default_budget=model.thinking_budgets.get(default),
        )
    return extra


def resolve(model):
    data = current_catalog(model)
    facts, sources = {}, {}
    for source, layer in (
        ("registry", data.get("registry", {})),
        ("provider", data.get("provider", {})),
        (
            "manual",
            {"max_output_tokens": model.provider_output_limit}
            if model.provider_output_limit is not None
            else {},
        ),
        ("manual", model.capability_overrides),
    ):
        for key, value in layer.items():
            if (
                not model.auto_thinking
                and source in ("provider", "registry")
                and key not in FLAGS + LIMITS
            ):
                continue
            facts[key], sources[key] = value, source
    if not model.auto_thinking:
        manual = {"wire": None}
        if (
            model.thinking_contract != "none"
            and model.capability_overrides.get("reasoning") is not False
        ):
            manual = legacy_facts(model)
        for key, value in manual.items():
            facts[key], sources[key] = value, "manual"
    elif "wire" not in facts and data:
        # Explicit adapter choice declares the Chat Completions wire dialect.
        kind = model.connection.discovery_type
        if kind in ("openai", "openrouter"):
            facts["wire"] = "native_effort" if kind == "openai" else "router_effort"
            sources["wire"] = "adapter"
    for key, value in model.reasoning_overrides.items():
        facts[key], sources[key] = value, "manual"
    if facts.get("reasoning") is False:
        for key, value in (("efforts", []), ("wire", None), ("default_effort", None)):
            facts[key], sources[key] = value, sources["reasoning"]
    elif facts.get("default_effort") not in facts.get("efforts", []):
        facts.pop("default_effort", None)
        sources.pop("default_effort", None)
    return facts, sources


VERIFICATION = {
    "manual": "operator_confirmed",
    "provider": "endpoint_declared",
    "registry": "registry_only",
    "adapter": "configured_adapter",
}


def reasoning_evidence(model, keys):
    facts, sources = resolve(model)
    catalog = current_catalog(model)
    return {
        key: {
            "value": facts.get(key),
            "source": sources.get(key, "unknown"),
            "verification": VERIFICATION.get(sources.get(key), "unknown"),
            "overridden": sources.get(key) == "manual",
            "conflicts": {
                name: layer[key]
                for name in ("provider", "registry")
                if key in (layer := catalog.get(name, {}))
                and layer[key] != facts.get(key)
            },
        }
        for key in keys
    }


def runtime_model(model):
    """Snapshot effective controls and limits for this turn without saving over admin fields."""
    facts, sources = resolve(model)
    result = copy(model)
    if facts.get("reasoning") is False:
        result.reasoning_policy = "hidden"
    if facts.get("context_window"):
        result.context_window = min(model.context_window, facts["context_window"])
    if facts.get("max_output_tokens"):
        result.max_output_tokens = min(
            model.max_output_tokens, facts["max_output_tokens"]
        )
    profile = build_profile(result, facts, sources)
    result.reasoning_profile = profile
    # Read-only scalar compatibility projection for existing clients.
    if (
        model.reasoning_overrides
        and not model.auto_thinking
        and profile.wire == model.thinking_contract
        and profile.wire != "none"
    ):
        result.thinking_levels = []
        for level in model.thinking_levels:
            try:
                profile.payload(
                    scalar_values(profile.wire, level, model.thinking_budgets)
                )
            except ValidationError:
                continue
            result.thinking_levels.append(level)
        if result.thinking_default not in result.thinking_levels:
            result.thinking_default = ""
    elif model.auto_thinking or model.reasoning_overrides or profile.supported is False:
        result.thinking_levels, result.thinking_default = [], ""
        for control in profile.controls:
            if control["type"] == "effort":
                result.thinking_levels = [
                    o["value"] for o in control["options"] if valid_level(o["value"])
                ]
                if control.get("default") in result.thinking_levels:
                    result.thinking_default = control["default"]
    result.reasoning_supported = profile.supported
    result.can_stream = facts.get("streaming") is not False
    result.can_chat = (
        facts.get("text_generation") is not False
        and facts.get("chat_completions") is not False
    )
    return result


def validate_reasoning_overrides(model):
    """Validate operator input before save, including inherited limits/defaults."""
    overrides = model.reasoning_overrides
    if not isinstance(overrides, dict):
        raise ValidationError("تنظیمات دستی استدلال نامعتبر است.")
    if not overrides:
        return
    bools = {
        "budget_required",
        "toggle_required",
        "reasoning",
        "reasoning_mandatory",
        "reasoning_toggle",
        "default_enabled",
        "effort_required",
    }
    checks = {
        "wire": lambda v: isinstance(v, str) and v in WIRE,
        "efforts": lambda v: isinstance(v, list) and levels(v) == v,
        "default_effort": valid_effort,
        "budget_presets": lambda v: isinstance(v, list)
        and 0 < len(v) <= 64
        and all(positive(n) for n in v)
        and len(set(v)) == len(v),
        "budget_tokens": lambda v: isinstance(v, dict)
        and set(v) == {"min", "max"}
        and all(positive(n) for n in v.values())
        and v["min"] <= v["max"],
        "default_budget": positive,
    }
    for key, value in overrides.items():
        valid = (
            type(value) is bool
            if key in bools
            else key in checks and checks[key](value)
        )
        if not valid:
            raise ValidationError("مقدار دستی استدلال یا نوع آن معتبر نیست.")
    facts, _ = resolve(model)
    if overrides.get("reasoning") is False:
        return
    budget = facts.get("budget_tokens", {})
    upper = (
        min(
            model.max_output_tokens or 0,
            facts.get("max_output_tokens", model.max_output_tokens or 0),
        )
        - 1
    )
    lo, hi = budget.get("min", 1), budget.get("max", upper)
    presets = facts.get("budget_presets", [])
    if (
        any(not lo <= n <= min(hi, upper) for n in overrides.get("budget_presets", []))
        or ("budget_tokens" in overrides and hi > upper)
        or (
            "default_budget" in overrides
            and (
                not lo <= overrides["default_budget"] <= min(hi, upper)
                or presets
                and overrides["default_budget"] not in presets
            )
        )
    ):
        raise ValidationError("بودجهٔ دستی باید داخل بازه و کمتر از سقف خروجی باشد.")
    if "default_effort" in overrides and overrides["default_effort"] not in facts.get(
        "efforts", []
    ):
        raise ValidationError("پیش‌فرض باید یکی از سطوح مجاز باشد.")
    wire = facts.get("wire")
    if wire == "kimi_preserved" and model.reasoning_policy != "preserve":
        raise ValidationError("قرارداد Kimi به سیاست preserve نیاز دارد.")
    if model.provider == "demo" and facts.get("reasoning"):
        raise ValidationError("مدل نمایشی از تنظیم استدلال پشتیبانی نمی‌کند.")
    if wire in WIRE:
        for kind, keys in (
            ("effort", ("efforts", "default_effort", "effort_required")),
            (
                "budget",
                (
                    "budget_tokens",
                    "budget_presets",
                    "default_budget",
                    "budget_required",
                ),
            ),
            ("toggle", ("reasoning_toggle", "default_enabled", "toggle_required")),
        ):
            if any(overrides.get(k) for k in keys) and kind not in WIRE[wire].controls:
                raise ValidationError("کنترل دستی با قرارداد انتخاب‌شده سازگار نیست.")
    if facts.get("reasoning_mandatory") and (
        overrides.get("reasoning_toggle") or overrides.get("default_enabled") is False
    ):
        raise ValidationError(
            "استدلال اجباری نمی‌تواند پیش‌فرض خاموش یا کلید خاموش‌کردن داشته باشد."
        )
