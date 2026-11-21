"""Normalize catalog evidence. Only allowlisted, typed facts cross this boundary."""

from copy import copy
from hashlib import sha256

from django.core.exceptions import ValidationError

from .thinking import valid_level

FLAGS = (
    "text_generation",
    "chat_completions",
    "reasoning",
    "vision",
    "image_generation",
    "tool_calling",
    "streaming",
    "structured_output",
    "json_mode",
)
LIMITS = ("context_window", "max_output_tokens")


def positive(value):
    return type(value) is int and 0 < value <= 2147483647


def validate_overrides(value):
    if not isinstance(value, dict) or any(
        not (key in FLAGS and type(v) is bool or key in LIMITS and positive(v))
        for key, v in value.items()
    ):
        raise ValidationError(
            "قابلیت دستی باید مقدار بولی یا سقف عددی مثبت و کلید معتبر داشته باشد."
        )


def strings(value):
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def levels(values):
    if (
        not isinstance(values, list)
        or len(values) > 64
        or not all(valid_level(v) for v in values)
    ):
        return []
    return list(dict.fromkeys(values))


def modalities(facts, inputs, outputs):
    if strings(inputs):
        facts["vision"] = "image" in inputs
    if strings(outputs):
        facts.update(
            text_generation="text" in outputs, image_generation="image" in outputs
        )


def registry_facts(row):
    facts = {}
    for key, target in (
        ("reasoning", "reasoning"),
        ("tool_call", "tool_calling"),
        ("structured_output", "structured_output"),
    ):
        if type(row.get(key)) is bool:
            facts[target] = row[key]
    limits = row.get("limit")
    if isinstance(limits, dict):
        for key, target in (
            ("context", "context_window"),
            ("output", "max_output_tokens"),
        ):
            if positive(limits.get(key)):
                facts[target] = limits[key]
    modes = row.get("modalities")
    if isinstance(modes, dict):
        modalities(facts, modes.get("input"), modes.get("output"))
    options = row.get("reasoning_options")
    for option in options if isinstance(options, list) else []:
        if isinstance(option, dict) and option.get("type") == "budget_tokens":
            facts["budget_tokens"] = {
                k: v
                for k, v in option.items()
                if k in ("min", "max") and type(v) is int and -1 <= v <= 2147483647
            }
        if isinstance(option, dict) and option.get("type") == "toggle":
            facts["reasoning_toggle"] = True
        if (
            isinstance(option, dict)
            and option.get("type") == "effort"
            and isinstance(option.get("values"), list)
        ):
            # Registry sentinels do not declare a literal wire value.
            facts["efforts"] = levels(
                [v for v in option["values"] if v is not None and v != "default"]
            )
    return facts


# An explicit null allowlist on OpenRouter means all documented gateway efforts.
# Missing supported_efforts carries no such promise. Other adapters do not use this list.
OPENROUTER_EFFORTS = ("max", "xhigh", "high", "medium", "low", "minimal", "none")


def openrouter_facts(facts, row):
    endpoints = row.get("endpoints")
    if strings(endpoints):
        facts["chat_completions"] = any(
            p in ("/chat/completions", "/api/v1/chat/completions") for p in endpoints
        )
    reasoning = row.get("reasoning")
    if not isinstance(reasoning, dict) or type(reasoning.get("mandatory")) is not bool:
        return
    facts["reasoning"] = True
    # The model-specific reasoning descriptor documents the nested chat parameter.
    facts["wire"] = "router_effort"
    facts["reasoning_mandatory"] = reasoning["mandatory"]
    if "supported_efforts" in reasoning:
        allowed = reasoning["supported_efforts"]
        if allowed is None:
            facts["efforts"] = list(OPENROUTER_EFFORTS)
        elif isinstance(allowed, list):
            facts["efforts"] = levels([s for s in allowed if s is not None])
        else:
            facts["efforts"] = []
    if valid_level(reasoning.get("default_effort")):
        facts["default_effort"] = reasoning["default_effort"]
    for source, target in (
        ("default_enabled", "default_enabled"),
        ("supports_max_tokens", "router_budget_supported"),
    ):
        if type(reasoning.get(source)) is bool:
            facts[target] = reasoning[source]


def provider_facts(row, kind):
    facts = {}
    caps = row.get("capabilities")
    if isinstance(caps, dict):
        for key in FLAGS:
            if type(caps.get(key)) is bool:
                facts[key] = caps[key]
    if kind == "lmstudio":
        if row.get("type") in ("llm", "embedding"):
            facts["text_generation"] = row["type"] == "llm"
        if isinstance(caps, dict) and type(caps.get("trained_for_tool_use")) is bool:
            facts["tool_calling"] = caps["trained_for_tool_use"]
        if positive(row.get("max_context_length")):
            facts["context_window"] = row["max_context_length"]
    architecture = row.get("architecture")
    if isinstance(architecture, dict):
        modalities(
            facts,
            architecture.get("input_modalities"),
            architecture.get("output_modalities"),
        )
    top = row.get("top_provider")
    for key, value in (
        ("context_window", row.get("context_length", row.get("context_window"))),
        (
            "max_output_tokens",
            top.get("max_completion_tokens")
            if isinstance(top, dict) and top.get("max_completion_tokens") is not None
            else row.get("max_output_tokens"),
        ),
    ):
        if positive(value):
            facts[key] = value
    if "supported_reasoning_efforts" in row:
        facts["efforts"] = levels(row["supported_reasoning_efforts"])
    params = row.get("supported_parameters")
    if isinstance(params, list) and all(
        isinstance(p, str) or (isinstance(p, dict) and isinstance(p.get("name"), str))
        for p in params
    ):
        names = set()
        for param in params:
            name = param.get("name") if isinstance(param, dict) else param
            if isinstance(name, str):
                names.add(name)
            if (
                name == "reasoning_effort"
                and isinstance(param, dict)
                and "options" in param
            ):
                facts["efforts"] = levels(param["options"])
        if names.intersection({"reasoning", "reasoning_effort"}):
            facts.setdefault("reasoning", True)
        if "reasoning_effort" in names:
            facts["wire"] = "native_effort"
        elif "reasoning" in names and kind == "openrouter":
            facts["wire"] = "router_effort"
        else:
            # Endpoint declares its parameter list but no supported effort dialect.
            facts["wire"] = None
        for param, flag in (
            ("tools", "tool_calling"),
            ("structured_outputs", "structured_output"),
        ):
            if kind == "openrouter" or param in names:
                facts.setdefault(flag, param in names)
        if "response_format" in names:
            facts.setdefault("json_mode", True)
    if facts.get("efforts") and "reasoning" not in facts:
        facts["reasoning"] = True
    if valid_level(row.get("default_reasoning_effort")):
        facts["default_effort"] = row["default_reasoning_effort"]
    if kind == "openrouter":
        openrouter_facts(facts, row)
    return facts


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


def resolve(model):
    data = model.discovery_data
    if data and (
        data.get("model_id") != model.model_id
        or not model.connection_id
        or data.get("connection") != connection_signature(model.connection)
    ):
        data = {}
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
            facts[key], sources[key] = value, source
    if not model.auto_thinking:
        if (
            model.thinking_contract != "none"
            and model.capability_overrides.get("reasoning") is not False
        ):
            for key, value in (
                ("reasoning", True),
                ("efforts", model.thinking_levels),
                ("wire", model.thinking_contract),
                ("default_effort", model.thinking_default),
            ):
                facts[key], sources[key] = value, "manual"
        else:
            facts["wire"], sources["wire"] = None, "manual"
    elif "wire" not in facts and data:
        # Explicit adapter choice declares the Chat Completions wire dialect.
        kind = model.connection.discovery_type
        if kind in ("openai", "openrouter"):
            facts["wire"] = "native_effort" if kind == "openai" else "router_effort"
            sources["wire"] = "adapter"
    if model.auto_thinking and facts.get("reasoning_mandatory") and "efforts" in facts:
        facts["efforts"] = [value for value in facts["efforts"] if value != "none"]
    if facts.get("reasoning") is False:
        for key, value in (("efforts", []), ("wire", None), ("default_effort", None)):
            facts[key], sources[key] = value, sources["reasoning"]
    elif facts.get("default_effort") not in facts.get("efforts", []):
        facts.pop("default_effort", None)
        sources.pop("default_effort", None)
    return facts, sources


def runtime_model(model):
    """Snapshot effective controls and limits for this turn without saving over admin fields."""
    facts, _ = resolve(model)
    result = copy(model)
    if model.auto_thinking or facts.get("reasoning") is False:
        result.thinking_contract, result.thinking_levels, result.thinking_default = (
            "none",
            [],
            "",
        )
        supported = facts.get("efforts", [])
        wire = facts.get("wire")
        if (
            facts.get("reasoning") is not False
            and supported
            and wire in ("native_effort", "router_effort")
        ):
            result.thinking_contract, result.thinking_levels = wire, supported
            default = facts.get("default_effort")
            result.thinking_default = default if default in supported else ""
            # OpenRouter default_effort applies when reasoning is enabled. Preserve
            # implicit gateway behavior unless the operator/user explicitly selects.
            if wire == "router_effort" and (
                default == "none" or facts.get("default_enabled") is not True
            ):
                result.thinking_default = ""
    if facts.get("reasoning") is False:
        result.reasoning_policy = "hidden"
    if facts.get("context_window"):
        result.context_window = min(model.context_window, facts["context_window"])
    if facts.get("max_output_tokens"):
        result.max_output_tokens = min(
            model.max_output_tokens, facts["max_output_tokens"]
        )
    result.can_stream = facts.get("streaming") is not False
    result.reasoning_supported = facts.get("reasoning")
    result.can_chat = (
        facts.get("text_generation") is not False
        and facts.get("chat_completions") is not False
    )
    return result
