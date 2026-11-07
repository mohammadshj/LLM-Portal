"""Provider boundary: no credentials or raw upstream errors reach API responses."""

import httpx
from django.conf import settings


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
    if not settings.LLM_API_KEY:
        raise ProviderError("کلید سرویس مدل در سرور تنظیم نشده است.")
    try:
        with httpx.Client(timeout=httpx.Timeout(45, connect=10)) as client:
            response = client.post(
                f"{settings.LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
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
