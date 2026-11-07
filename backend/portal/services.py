from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import Account, Conversation, LanguageModel, Message, ModelUsage
from .providers import ProviderError, complete


def send_message(user, conversation, content, model_ids):
    # Serialize requests per user across workers. Holding the lock across the
    # bounded provider call is deliberately simple for this low-traffic MVP.
    Account.objects.get_or_create(user=user)
    with transaction.atomic():
        account = Account.objects.select_for_update().get(user=user)
        try:
            conversation = Conversation.objects.select_for_update().get(
                pk=conversation.pk, user=user
            )
        except Conversation.DoesNotExist:
            raise ValidationError("این گفتگو دیگر وجود ندارد.") from None
        models = list(
            LanguageModel.objects.filter(pk__in=model_ids, enabled=True).order_by("id")
        )
        if len(models) != len(model_ids):
            raise ValidationError("یکی از مدل‌ها موجود یا فعال نیست.")
        history = list(conversation.messages.select_related("model"))
        requests = []
        for model in models:
            # Comparison branches only include this model's previous replies.
            messages = [
                {"role": m.role, "content": m.content}
                for m in history
                if m.role == "user" or m.model_id == model.id
            ]
            messages.append({"role": "user", "content": content})
            # UTF-8 bytes are a conservative bound for supported byte-BPE
            # tokenizers; include framing allowance and reserve maximum output.
            bound = sum(len(m["content"].encode()) + 32 for m in messages) + 32
            reserve = bound + model.max_output_tokens
            if reserve > model.context_window:
                raise ValidationError(
                    "ظرفیت گفتگو برای مدل انتخابی کافی نیست؛ گفتگوی تازه بسازید."
                )
            requests.append((model, messages, reserve))
        if account.tokens_used + sum(r[2] for r in requests) > account.token_limit:
            raise ValidationError("سهمیهٔ باقی‌مانده برای این درخواست کافی نیست.")
        Message.objects.create(conversation=conversation, role="user", content=content)
        # Failures are returned per model; successful paid calls remain recorded.
        errors = []
        for model, messages, reserve in requests:
            try:
                text, incoming, outgoing = complete(model, messages)
            except ProviderError as exc:
                errors.append({"model": model.name, "detail": str(exc)})
                continue
            account.tokens_used += incoming + outgoing
            usage, _ = ModelUsage.objects.get_or_create(user=user, model=model)
            usage.input_tokens += incoming
            usage.output_tokens += outgoing
            usage.save(update_fields=["input_tokens", "output_tokens"])
            Message.objects.create(
                conversation=conversation,
                role="assistant",
                content=text,
                model=model,
                input_tokens=incoming,
                output_tokens=outgoing,
            )
        account.save(update_fields=["tokens_used"])
        return errors
