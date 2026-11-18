"""Provider boundary: no credentials or raw upstream errors reach API responses."""

import os

import httpx
from django.core.exceptions import ValidationError


class ProviderError(Exception):
    pass


def complete(model, messages):
    if model.provider == "demo":
        prompt = messages[-1]["content"]
        text = f"پاسخ نمایشی {model.name}: «{prompt}»\nاین پاسخ برای آزمون سامانه است و توسط مدل واقعی تولید نشده است."
        text = text.encode()[: model.max_output_tokens].decode("utf-8", errors="ignore")
        return (
            text,
            sum(len(m["content"].encode()) for m in messages),
            len(text.encode()),
        )
    if model.provider != "openai":
        raise ProviderError("نوع ارتباط این مدل پشتیبانی نمی‌شود.")
    connection = model.connection
    if connection is None or not connection.enabled:
        raise ProviderError("اتصال سرویس مدل تنظیم نشده یا غیرفعال است.")
    try:
        # Revalidate even if a non-admin script bypassed Django form validation.
        connection.clean()
    except ValidationError:
        raise ProviderError("تنظیمات اتصال سرویس مدل معتبر نیست.") from None
    headers = {}
    if connection.api_key_env:
        key = os.environ.get(connection.api_key_env, "").strip()
        if not key:
            raise ProviderError("کلید این اتصال در محیط سرور تنظیم نشده است.")
        headers["Authorization"] = f"Bearer {key}"

    try:
        with httpx.Client(
            timeout=httpx.Timeout(45, connect=10), follow_redirects=False
        ) as client:
            response = client.post(
                f"{connection.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": model.model_id,
                    "messages": messages,
                    "max_tokens": model.max_output_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            usage = data["usage"]
            incoming, outgoing = usage["prompt_tokens"], usage["completion_tokens"]
            if (
                not isinstance(content, str)
                or not content.strip()
                or type(incoming) is not int
                or type(outgoing) is not int
                or min(incoming, outgoing) < 0
            ):
                raise ValueError
            return content, incoming, outgoing
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
        raise ProviderError(
            "دریافت پاسخ معتبر از سرویس مدل ممکن نشد. دوباره تلاش کنید."
        ) from None
