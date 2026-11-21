"""Allowlisted metadata parsers for catalog and registry APIs."""

from .reasoning_contracts import WIRE

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


def strings(value):
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def valid_effort(value):
    # Modern controls carry an opaque string, independent of the legacy slug column.
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and value.strip() == value
        and value.isprintable()
    )


def levels(values):
    if (
        not isinstance(values, list)
        or len(values) > 64
        or not all(valid_effort(v) for v in values)
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
    option_facts(facts, row.get("reasoning_options"), registry=True)
    return facts


SEMANTICS = {"minimal", "low", "medium", "high", "maximum", "disabled", "unknown"}


def option_facts(facts, options, registry=False):
    if not isinstance(options, list) or len(options) > 16:
        return
    for opt in options:
        if not isinstance(opt, dict):
            continue
        kind = opt.get("type")
        if kind == "toggle":
            facts["reasoning_toggle"] = True
            if type(opt.get("default")) is bool:
                facts["default_enabled"] = opt["default"]
        elif kind == "budget_tokens":
            limits = {k: opt[k] for k in ("min", "max") if positive(opt.get(k))}
            facts["budget_tokens"] = limits
            values = opt.get("values", [])
            if (
                isinstance(values, list)
                and len(values) <= 64
                and all(positive(n) for n in values)
            ):
                facts["budget_presets"] = list(dict.fromkeys(values))
            else:
                # Unreadable discrete choices do not authorize a continuous range.
                facts.update(budget_presets=[], budget_tokens={})
            if positive(opt.get("default")):
                facts["default_budget"] = opt["default"]
        elif kind == "effort" and isinstance(opt.get("values"), list):
            values, labels, semantics = [], {}, {}
            for item in opt["values"][:65]:
                if isinstance(item, dict):
                    value = item.get("value")
                    if not valid_effort(value):
                        continue
                    label, meaning = item.get("label"), item.get("semantic_level")
                    if (
                        isinstance(label, str)
                        and len(label) <= 80
                        and label.isprintable()
                    ):
                        labels[value] = label
                    if isinstance(meaning, str) and meaning in SEMANTICS:
                        semantics[value] = meaning
                    values.append(value)
                elif item is not None and not (registry and item == "default"):
                    values.append(item)
            facts.update(
                efforts=levels(values), effort_labels=labels, effort_semantics=semantics
            )
            if valid_effort(opt.get("default")):
                facts["default_effort"] = opt["default"]
        else:
            continue
        if type(opt.get("required")) is bool:
            name = "budget" if kind == "budget_tokens" else kind
            facts[name + "_required"] = opt["required"]
        facts.setdefault("reasoning", True)


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
    facts.setdefault("reasoning", True)
    # The model-specific reasoning descriptor documents the nested chat parameter.
    facts["wire"] = "router_effort"
    facts["reasoning_mandatory"] = reasoning["mandatory"]
    if type(reasoning.get("default_enabled")) is bool:
        facts["reasoning_toggle"] = not reasoning["mandatory"]
    facts["router_budget_supported"] = reasoning.get("supports_max_tokens") is True
    facts["effort_semantics"] = {
        **facts.get("effort_semantics", {}),
        "none": "disabled",
    }
    if "supported_efforts" in reasoning:
        allowed = reasoning["supported_efforts"]
        if allowed is None:
            facts["efforts"] = list(OPENROUTER_EFFORTS)
        elif isinstance(allowed, list):
            facts["efforts"] = levels([s for s in allowed if s is not None])
        else:
            facts["efforts"] = []
    if valid_effort(reasoning.get("default_effort")):
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
                if type(param.get("required")) is bool:
                    facts["effort_required"] = param["required"]
        if names.intersection({"reasoning", "reasoning_effort"}):
            facts.setdefault("reasoning", True)
        if "reasoning_effort" in names and kind != "openrouter":
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
        if kind != "openrouter":
            # Some gateways publish leaf parameter descriptors for Chat Completions.
            descriptors = {p["name"]: p for p in params if isinstance(p, dict)}
            modes = descriptors.get("thinking.type", {}).get("options")
            if (
                strings(modes)
                and "enabled" in modes
                and set(modes) <= {"enabled", "disabled"}
            ):
                facts.setdefault("reasoning", True)
                facts["reasoning_toggle"] = "disabled" in modes
                budget = descriptors.get("thinking.budget_tokens")
                if budget:
                    option_facts(
                        facts,
                        [
                            {
                                **budget,
                                "type": "budget_tokens",
                                "values": budget.get("options", []),
                            }
                        ],
                    )
                facts["wire"] = "thinking_controls"
    if facts.get("efforts") and "reasoning" not in facts:
        facts["reasoning"] = True
    if type(row.get("supports_reasoning_toggle")) is bool:
        facts["reasoning_toggle"] = row["supports_reasoning_toggle"]
        if facts["reasoning_toggle"]:
            facts.setdefault("reasoning", True)
    if valid_effort(row.get("default_reasoning_effort")):
        facts["default_effort"] = row["default_reasoning_effort"]
    if "reasoning_effort" in row and isinstance(row["reasoning_effort"], list):
        facts["efforts"] = levels(row["reasoning_effort"])
        if facts["efforts"]:
            facts.setdefault("reasoning", True)
    option_facts(facts, row.get("reasoning_options"))
    if "disabled_reasoning_efforts" in row:
        facts["disabled_efforts"] = levels(row["disabled_reasoning_efforts"])
    if type(row.get("reasoning_mandatory")) is bool:
        facts["reasoning_mandatory"] = row["reasoning_mandatory"]
    if "reasoning_contract" in row:
        wire = row["reasoning_contract"]
        facts["wire"] = wire if isinstance(wire, str) and wire in WIRE else None
    if kind == "openrouter":
        openrouter_facts(facts, row)
    if facts.get("reasoning_mandatory") is True:
        facts.setdefault("reasoning", True)
    # An explicit parameter allowlist can rule out a contradictory catalog extension.
    if isinstance(params, list) and "wire" in facts and facts["wire"] in WIRE:
        roots = {
            "native_effort": {"reasoning_effort"},
            "effort": {"reasoning_effort"},
            "router_effort": {"reasoning"},
            "toggle_effort": {"thinking", "reasoning_effort"},
            "thinking_controls": {"thinking"},
            "budget_tokens": {"thinking"},
            "toggle": {"thinking"},
            "kimi_preserved": {"thinking"},
        }
        names = {
            p if isinstance(p, str) else p.get("name")
            for p in params
            if isinstance(p, str)
            or isinstance(p, dict)
            and isinstance(p.get("name"), str)
        }
        if "thinking.type" in names:
            names.add("thinking")
        if not roots.get(facts["wire"], set()).issubset(names):
            facts["wire"] = None
        elif facts["wire"] == "thinking_controls" and "reasoning_effort" not in names:
            facts["efforts"] = []
    return facts
