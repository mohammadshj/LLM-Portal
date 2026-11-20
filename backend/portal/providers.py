"""Server-side OpenAI Chat Completions client (including DeepSeek)."""

import asyncio
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass

import httpx
from django.conf import settings
from django.core.exceptions import ValidationError

from .thinking import parameters
from .tokens import parse_usage

logger = logging.getLogger(__name__)
MAX_EVENT_CHARS = 2 * 1024 * 1024


MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class ProviderError(Exception):
    """The exception message and code are safe for clients; never attach an HTTP body."""

    def __init__(self, message, *, code="provider_error", status=None, usage=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.usage = usage


@dataclass(frozen=True)
class ProviderEvent:
    kind: str
    text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None


def _log(model, code, status, started, *, warning=True):
    # Only controlled categories and local database IDs. URLs, response bodies,
    # upstream request IDs, model output and exception strings can contain private data.
    record = {
        "event": "llm_provider",
        "code": code,
        "http_status": status,
        "model_pk": model.pk,
        "connection_pk": model.connection_id,
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
    logger.log(logging.WARNING if warning else logging.INFO, json.dumps(record))


@contextmanager
def _diagnostics(model):
    started = time.monotonic()
    details = {"status": None, "usage": None}
    try:
        yield details
    except (httpx.TimeoutException, TimeoutError):
        error = ProviderError("مهلت پاسخ‌گویی سرویس مدل پایان یافت.", code="timeout")
    except (httpx.ConnectError, httpx.ProxyError):
        error = ProviderError("اتصال به سرویس مدل برقرار نشد.", code="connection")
    except httpx.TransportError:
        error = ProviderError(
            "ارتباط با سرویس مدل هنگام انتقال پاسخ قطع شد.", code="transport"
        )
    except (UnicodeError, json.JSONDecodeError):
        error = ProviderError(
            "سرویس مدل پاسخ JSON معتبر ارسال نکرد.", code="invalid_json"
        )
    except ProviderError as exc:
        error = exc
    else:
        _log(model, "completed", details["status"], started, warning=False)
        return
    error.status = details["status"]
    error.usage = details["usage"]
    _log(model, error.code, error.status, started)
    raise error from None


def _timeout():
    return httpx.Timeout(
        settings.LLM_READ_TIMEOUT, connect=settings.LLM_CONNECT_TIMEOUT
    )


def _target(model, messages, level=None):
    if model.provider != "openai":
        raise ProviderError("نوع ارتباط این مدل پشتیبانی نمی‌شود.", code="configuration")
    connection = model.connection
    if connection is None or not connection.enabled:
        raise ProviderError(
            "اتصال سرویس مدل تنظیم نشده یا غیرفعال است.", code="configuration"
        )
    try:
        connection.clean()
    except ValidationError:
        raise ProviderError(
            "تنظیمات اتصال سرویس مدل معتبر نیست.", code="configuration"
        ) from None
    headers = {"Accept-Encoding": "identity"}
    if connection.api_key_env:
        key = os.environ.get(connection.api_key_env, "").strip()
        if not key:
            raise ProviderError(
                "کلید این اتصال در محیط سرور تنظیم نشده است.", code="configuration"
            )
        headers["Authorization"] = f"Bearer {key}"
    return (
        f"{connection.base_url}/chat/completions",
        headers,
        {
            "model": model.model_id,
            "messages": messages,
            **parameters(model.thinking_contract, level or model.thinking_default),
            model.output_parameter: model.max_output_tokens,
        },
    )


def _check_http(status):
    if 200 <= status < 300:
        return
    if status in (401, 403):
        message = "سرویس مدل دسترسی این اتصال را نپذیرفت. مدیر سامانه مجوز اتصال را بررسی کند."
    elif status == 429:
        message = "سقف درخواست یا اعتبار سرویس مدل رسیده است. بعداً تلاش کنید."
    elif status in (400, 422):
        message = "سرویس مدل درخواست را نپذیرفت. شناسهٔ مدل، ظرفیت گفتگو و پارامترهای اتصال را بررسی کنید."
    elif status == 402:
        message = "اعتبار اتصال نزد سرویس مدل کافی نیست."
    elif status == 404:
        message = "نشانی سرویس یا شناسهٔ مدل در سرویس پیدا نشد."
    elif status >= 500:
        message = "سرویس مدل موقتاً دچار خطا شده است. بعداً تلاش کنید."
    else:
        message = "سرویس مدل درخواست را با خطای HTTP پاسخ داد."
    raise ProviderError(f"{message} (HTTP {status})", code=f"http_{status}")


def _usage_event(data, details):
    counts = parse_usage(data)
    if counts is not None:
        details["usage"] = counts
        return ProviderEvent(
            "usage",
            input_tokens=counts.incoming,
            output_tokens=counts.outgoing,
            total_tokens=counts.total,
            reasoning_tokens=counts.reasoning,
        )


def _envelope_usage(data, details):
    if not isinstance(data, dict):
        raise ProviderError(
            "ساختار پاسخ سرویس مدل معتبر نیست.", code="invalid_envelope"
        )
    event = _usage_event(data.get("usage"), details)
    if data.get("error"):
        raise ProviderError(
            "سرویس مدل هنگام تولید پاسخ خطا گزارش کرد.", code="upstream_error"
        )
    return event


def _choice(data):
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderError(
            "پاسخ سرویس مدل فاقد گزینهٔ پاسخ معتبر است.", code="invalid_choices"
        )
    return choices[0]


def _text(message):
    if not isinstance(message, dict):
        raise ProviderError(
            "پیام مدل در پاسخ سرویس معتبر نیست.", code="invalid_message"
        )
    content = message.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(isinstance(part, dict) for part in content):
        parts = [
            part.get("text")
            for part in content
            if part.get("type") in ("text", "output_text")
        ]
        if all(isinstance(part, str) for part in parts):
            return "".join(parts)
    raise ProviderError(
        "قالب متن پاسخ سرویس مدل پشتیبانی نمی‌شود.", code="invalid_content"
    )


def _check_answer(visible, reasoning, finish):
    if finish == "insufficient_system_resource":
        raise ProviderError(
            "منابع سرویس مدل برای تکمیل پاسخ کافی نبود.", code="upstream_capacity"
        )
    if finish == "content_filter":
        raise ProviderError(
            "سرویس مدل پاسخ را طبق سیاست محتوای خود متوقف کرد.", code="filtered"
        )
    if finish in ("tool_calls", "function_call"):
        raise ProviderError(
            "این گفتگو از فراخوانی ابزار پشتیبانی نمی‌کند.", code="unsupported_tool"
        )
    if visible and finish == "length":
        raise ProviderError(
            "پاسخ با رسیدن به سقف توکن ناتمام ماند.", code="output_limit"
        )
    if not visible:
        if finish == "length":
            raise ProviderError(
                "سقف توکن خروجی پیش از دریافت متن پاسخ رسید. مدیر سامانه سقف خروجی مدل را بررسی کند.",
                code="output_limit",
            )
        if reasoning:
            raise ProviderError(
                "مدل فقط بخش استدلال را برگرداند و متن پاسخ نهایی خالی بود.",
                code="reasoning_only",
            )
        raise ProviderError(
            "سرویس مدل متن پاسخ نهایی را برنگرداند.", code="empty_answer"
        )


def _reasoning(message):
    value = message.get("reasoning_content")
    if value is not None and not isinstance(value, str):
        raise ProviderError("قالب استدلال سرویس معتبر نیست.", code="invalid_reasoning")
    if message.get("tool_calls") or message.get("function_call"):
        raise ProviderError(
            "این گفتگو از فراخوانی ابزار پشتیبانی نمی‌کند.", code="unsupported_tool"
        )
    return value


def _json_events(data, details, expose):
    usage = _envelope_usage(data, details)
    if usage:
        yield usage
    choice = _choice(data)
    message = choice.get("message")
    text = _text(message)
    reasoning = _reasoning(message)
    if reasoning is not None and expose:
        yield ProviderEvent("reasoning_delta", text=reasoning)
    if text:
        yield ProviderEvent("delta", text=text)
    _check_answer(text.strip(), bool(reasoning), choice.get("finish_reason"))
    yield ProviderEvent("done")


def _demo(model, messages):
    prompt = messages[-1]["content"]
    text = f"پاسخ نمایشی {model.name}: «{prompt}»\nاین پاسخ برای آزمون سامانه است و توسط مدل واقعی تولید نشده است."
    text = text.encode()[: model.max_output_tokens].decode("utf-8", errors="ignore")
    return text, sum(len(m["content"].encode()) for m in messages), len(text.encode())


def complete(model, messages):
    """Legacy synchronous JSON path; unknown provider token counts return None."""
    if model.provider == "demo":
        return _demo(model, messages)
    with _diagnostics(model) as details:
        url, headers, payload = _target(model, messages)
        with httpx.Client(timeout=_timeout(), follow_redirects=False) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                details["status"] = response.status_code
                _check_http(response.status_code)
                _check_encoding(response)
                body = bytearray()
                for chunk in response.iter_bytes():
                    _append_json(body, chunk)
            events = list(_json_events(json.loads(body), details, expose=False))
            text = next(event.text for event in events if event.kind == "delta")
            counts = details["usage"]
            return (
                text,
                counts.incoming if counts else None,
                counts.outgoing if counts else None,
            )


def _too_large():
    return ProviderError("حجم پاسخ سرویس از حد مجاز گذشت.", code="response_limit")


def _check_encoding(response):
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise ProviderError(
            "سرویس قالب انتقال درخواست‌شده را رعایت نکرد.", code="unsupported_encoding"
        )


def _append_json(body, chunk):
    if len(body) + len(chunk) > MAX_JSON_BYTES:
        raise _too_large()
    body.extend(chunk)


async def _bounded_bytes(response):
    _check_encoding(response)
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise _too_large()
        yield chunk


async def _lines(response):
    # Split across TCP and UTF-8 boundaries without buffering an unbounded line.
    partial = bytearray()
    trailing_cr = False
    async for chunk in _bounded_bytes(response):
        if not chunk:
            continue
        if trailing_cr and chunk.startswith(b"\n"):
            chunk = chunk[1:]
        trailing_cr = chunk.endswith(b"\r")
        start = 0
        for separator in re.finditer(rb"\r\n|\r|\n", chunk):
            if len(partial) + separator.start() - start > MAX_EVENT_CHARS:
                raise _too_large()
            partial.extend(chunk[start : separator.start()])
            yield partial.decode()
            partial.clear()
            start = separator.end()
        if len(partial) + len(chunk) - start > MAX_EVENT_CHARS:
            raise _too_large()
        partial.extend(chunk[start:])
    if partial:
        yield partial.decode()


async def _sse_data(response):
    lines = []
    size = 0
    async for line in _lines(response):
        if line == "" and lines:
            yield "\n".join(lines)
            lines = []
            size = 0
        elif line.startswith("data:") or line == "data":
            value = line.partition(":")[2].removeprefix(" ")
            size += len(value) + 1
            if size > MAX_EVENT_CHARS:
                raise _too_large()
            lines.append(value)
    if lines:
        raise ProviderError(
            "ارتباط پیش از تکمیل رویداد پاسخ قطع شد.", code="stream_incomplete"
        )


async def _stream_chunks(response, details, expose):
    visible = reasoning = False
    finish = None
    ended = False
    async for raw in _sse_data(response):
        if raw.strip() == "[DONE]":
            ended = True
            break
        data = json.loads(raw)
        usage = _envelope_usage(data, details)
        if usage is not None:
            yield usage
        # A terminal usage-only event legitimately has no choices.
        if data.get("choices") == [] and isinstance(data.get("usage"), dict):
            continue
        choice = _choice(data)
        delta = choice.get("delta")
        if delta is None and choice.get("finish_reason") is not None:
            delta = {}
        text = _text(delta)
        part = _reasoning(delta)
        reasoning |= bool(part)
        if expose and part is not None:
            yield ProviderEvent("reasoning_delta", text=part)
        if text:
            visible |= bool(text.strip())
            yield ProviderEvent("delta", text=text)
        if choice.get("finish_reason") is not None:
            finish = choice["finish_reason"]
    if not ended and not finish:
        raise ProviderError(
            "ارتباط پیش از دریافت پایان پاسخ سرویس قطع شد.", code="stream_incomplete"
        )
    _check_answer(visible, reasoning, finish)
    yield ProviderEvent("done")


async def stream_complete(model, messages, level=None):
    """Yield visible deltas as bytes arrive. One POST per model; closing releases the HTTP socket."""
    if model.provider == "demo":
        text, incoming, outgoing = _demo(model, messages)
        yield ProviderEvent("delta", text=text)
        yield ProviderEvent("usage", input_tokens=incoming, output_tokens=outgoing)
        yield ProviderEvent("done")
        return

    with _diagnostics(model) as details:
        url, headers, payload = _target(model, messages, level)
        expose = (
            model.reasoning_policy != "hidden"
            and (level or model.thinking_default) != "off"
        )
        if model.connection.streaming_enabled:
            payload["stream"] = True
            if model.stream_usage_option:
                payload["stream_options"] = {"include_usage": True}
        async with asyncio.timeout(settings.LLM_TOTAL_TIMEOUT):
            async with httpx.AsyncClient(
                timeout=_timeout(), follow_redirects=False
            ) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=payload
                ) as response:
                    details["status"] = response.status_code
                    _check_http(response.status_code)
                    mime = (
                        response.headers.get("content-type", "")
                        .partition(";")[0]
                        .strip()
                        .lower()
                    )
                    if mime == "text/event-stream":
                        async for event in _stream_chunks(response, details, expose):
                            yield event
                    else:
                        # Some compatible gateways ignore stream=true and return one JSON object.
                        # For providers that reject stream, an operator can disable it per connection.
                        body = bytearray()
                        async for chunk in _bounded_bytes(response):
                            _append_json(body, chunk)
                        for event in _json_events(json.loads(body), details, expose):
                            yield event
