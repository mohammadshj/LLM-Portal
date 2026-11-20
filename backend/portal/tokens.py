"""Completion tokens include any reported reasoning subset."""

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rest_framework.exceptions import ValidationError


@lru_cache(maxsize=4)
def _local_tokenizer(path, modified):
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(path))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def input_counter(name):
    if not name:
        return lambda text: len(text.encode())
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", name):
        raise ValidationError("نام توکنایزر معتبر نیست.")
    root = Path(os.environ.get("LLM_TOKENIZER_DIR", "/opt/portal/tokenizers")).resolve()
    path = (root / (name + ".json")).resolve()
    try:
        if path.parent != root:
            raise ValueError
        tokenizer = _local_tokenizer(path, path.stat().st_mtime_ns)
    except Exception:
        raise ValidationError("توکنایزر محلی این مدل در دسترس نیست.") from None
    return lambda text: len(tokenizer.encode(text, add_special_tokens=False).ids)


@dataclass(frozen=True)
class Usage:
    incoming: int | None
    outgoing: int | None
    total: int | None
    reasoning: int | None = None


def valid_count(value):
    return type(value) is int and 0 <= value <= 2147483647


def parse_usage(data):
    if not isinstance(data, dict):
        return None
    first = data.get("prompt_tokens", data.get("input_tokens"))
    last = data.get("completion_tokens", data.get("output_tokens"))
    total = data.get("total_tokens")
    if any(n is not None and not valid_count(n) for n in (first, last, total)):
        return None
    if total is None and first is not None and last is not None:
        total = first + last
    elif total is not None:
        if first is not None and last is None:
            last = total - first
        elif last is not None and first is None:
            first = total - last
        if first is not None and (min(first, last) < 0 or first + last != total):
            return None
    details = data.get("completion_tokens_details", data.get("output_tokens_details"))
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
    ceiling = last if last is not None else total
    if not valid_count(reasoning) or (ceiling is not None and reasoning > ceiling):
        reasoning = None
    if all(v is None for v in (first, last, total, reasoning)):
        return None
    return Usage(first, last, total, reasoning)
