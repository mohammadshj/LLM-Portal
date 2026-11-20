"""Reserve, call and settle are separate operations. No provider I/O inside atomic()."""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Account, Conversation, LanguageModel, Message, ModelUsage

log = logging.getLogger(__name__)
LEASE = timedelta(seconds=120)
TURN_DEADLINE = timedelta(minutes=10)
EXPIRED = "مهلت درخواست به پایان رسید. دوباره تلاش کنید."


class RequestConflict(ValidationError):
    status_code = 409


@dataclass
class Job:
    reply_id: int
    model: LanguageModel
    messages: list


def _locked_account(user_id):
    account, _ = Account.objects.get_or_create(user_id=user_id)
    return Account.objects.select_for_update().get(pk=account.pk)


def _turn_status(turn):
    statuses = set(turn.replies.values_list("status", flat=True))
    if "running" in statuses:
        return "running"
    if statuses == {"completed"}:
        return "completed"
    if "completed" in statuses:
        return "partial"
    return "cancelled" if turn.cancel_requested else "failed"


def _close_turn_if_done(turn):
    status = _turn_status(turn)
    if status != "running":
        turn.status = status
        turn.lease_until = None
        turn.save(update_fields=["status", "lease_until"])


def _expire_locked(user_id, now):
    # Caller owns Account lock. Recheck expiry under the turn lock because an
    # owner may renew its lease between the scheduler scan and this transaction.
    stale = list(
        Message.objects.select_for_update()
        .filter(
            conversation__user_id=user_id,
            role="user",
            status="running",
            lease_until__lte=now,
        )
        .order_by("id")
        .select_for_update(of=("self",))
    )
    for turn in stale:
        turn.replies.filter(status="running").update(
            status="cancelled" if turn.cancel_requested else "failed",
            error=EXPIRED,
            reserved_tokens=0,
            usage_source="unknown",
        )
        _close_turn_if_done(turn)
        log.warning("llm_reservation_expired turn_id=%s", turn.pk)
    return len(stale)


def recover_reservations():
    users = (
        Message.objects.filter(
            role="user", status="running", lease_until__lte=timezone.now()
        )
        .order_by()
        .values_list("conversation__user_id", flat=True)
        .distinct()
    )
    count = 0
    for user_id in list(users):
        with transaction.atomic():
            if Account.objects.select_for_update().filter(user_id=user_id).first():
                count += _expire_locked(user_id, timezone.now())
    return count


def should_cancel(turn_id):
    now = timezone.now()
    # The watcher calls this while waiting for upstream, even when no deltas arrive.
    active = Message.objects.filter(
        pk=turn_id,
        status="running",
        cancel_requested=False,
        lease_until__gt=now,
        created_at__gt=now - TURN_DEADLINE,
    )
    if active.filter(lease_until__lt=now + LEASE / 2).update(lease_until=now + LEASE):
        return False
    return not active.exists()


def request_cancel(user, conversation, request_id):
    # Cross-worker signal, scoped to an individual request UUID so delayed stops
    # cannot cancel a subsequent send. Settlement remains the owner's job.
    return bool(
        Message.objects.filter(
            conversation_id=conversation.pk,
            conversation__user=user,
            role="user",
            request_id=request_id,
            status="running",
        ).update(cancel_requested=True)
    )


def delete_conversation(user, conversation):
    with transaction.atomic():
        _locked_account(user.pk)
        chat = (
            Conversation.objects.select_for_update()
            .filter(pk=conversation.pk, user=user)
            .first()
        )
        if chat is None:
            return
        _expire_locked(user.pk, timezone.now())
        if chat.messages.filter(role="user", status="running").exists():
            raise RequestConflict("پیش از حذف گفتگو، درخواست فعال را متوقف کنید.")
        chat.delete()


def _admission_plan(chat, models, content):
    # A model gets only question/answer pairs it actually completed. This
    # excludes orphan legacy questions, failed branches and stopped partials.
    prior = (
        chat.messages.filter(
            role="assistant",
            status="completed",
            model_id__in=[m.pk for m in models],
            parent__isnull=False,
        )
        .order_by("id")
        .values_list("model_id", "parent__content", "content")
    )
    histories = {model.pk: [] for model in models}
    for model_id, question, answer in prior:
        histories[model_id].extend(
            [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
        )
    plans = []
    for model in models:
        messages = histories[model.pk]
        messages.append({"role": "user", "content": content})
        bound = sum(len(m["content"].encode()) + 32 for m in messages) + 32
        hold = bound + model.max_output_tokens
        if hold > model.context_window or model.max_output_tokens < 1:
            raise ValidationError(
                "ظرفیت گفتگو برای مدل انتخابی کافی نیست؛ گفتگوی تازه بسازید."
            )
        plans.append((model, messages, bound, hold))
    return plans


def reserve_turn(user, conversation, content, model_ids, request_id=None):
    if not 1 <= len(model_ids) <= 3 or len(set(model_ids)) != len(model_ids):
        raise ValidationError("یک تا سه مدل متفاوت انتخاب کنید.")
    with transaction.atomic():
        account = _locked_account(user.pk)
        _expire_locked(user.pk, timezone.now())
        chat = (
            Conversation.objects.select_for_update()
            .filter(
                user=user,
                pk=conversation.pk,
                created_at__gte=timezone.now() - timedelta(days=30),
            )
            .first()
        )
        if chat is None:
            raise ValidationError("این گفتگو دیگر وجود ندارد.")
        if request_id and chat.messages.filter(request_id=request_id).exists():
            raise RequestConflict(
                "این درخواست قبلاً ثبت شده است. تاریخچه را بررسی کنید."
            )
        if chat.messages.filter(role="user", status="running").exists():
            raise RequestConflict("در این گفتگو درخواستی در حال پردازش است.")
        models = list(
            LanguageModel.objects.filter(pk__in=model_ids, enabled=True)
            .select_related("connection")
            .order_by("id")
        )
        if len(models) != len(model_ids):
            raise ValidationError("یکی از مدل‌ها موجود یا فعال نیست.")
        plans = _admission_plan(chat, models, content)
        open_holds = (
            Message.objects.filter(
                conversation__user=user, role="assistant", status="running"
            ).aggregate(total=Sum("reserved_tokens"))["total"]
            or 0
        )
        if (
            account.tokens_used + open_holds + sum(p[3] for p in plans)
            > account.token_limit
        ):
            raise ValidationError("سهمیهٔ باقی‌مانده برای این درخواست کافی نیست.")
        turn = Message.objects.create(
            conversation=chat,
            role="user",
            content=content,
            status="running",
            request_id=request_id or uuid.uuid4(),
            lease_until=timezone.now() + LEASE,
        )
        jobs = []
        for model, messages, bound, hold in plans:
            reply = Message.objects.create(
                conversation=chat,
                role="assistant",
                model=model,
                parent=turn,
                status="running",
                input_bound=bound,
                reserved_tokens=hold,
            )
            jobs.append(Job(reply.pk, model, messages))
        return turn, jobs


def _usage(reply, text, usage):
    if usage and all(type(n) is int and n >= 0 for n in usage):
        return *usage, "reported"
    if not text:
        return 0, 0, "unknown"
    # Missing upstream usage: a visible estimate, bounded by the held budget.
    output = min(reply.reserved_tokens - reply.input_bound, len(text.encode()))
    return reply.input_bound, output, "estimated"


def finish_reply(reply_id, status, text="", usage=None, error=""):
    if status not in {"completed", "failed", "cancelled"}:
        raise ValueError("Invalid reply state")
    with transaction.atomic():
        try:
            user_id, parent_id = (
                Message.objects.filter(pk=reply_id)
                .values_list("conversation__user_id", "parent_id")
                .get()
            )
        except Message.DoesNotExist:
            return "cancelled"  # Owner removed after the lease was recovered.
        account = _locked_account(user_id)
        turn = Message.objects.select_for_update().filter(pk=parent_id).first()
        if turn is None:
            return "cancelled"
        reply = Message.objects.get(pk=reply_id)
        if reply.status != "running":
            return reply.status  # Fence late writers; settle each reply just once.
        if turn.cancel_requested or status == "cancelled":
            status = "cancelled"
            if not turn.cancel_requested:
                turn.cancel_requested = True
                turn.save(update_fields=["cancel_requested"])
        incoming, outgoing, source = _usage(reply, text, usage)
        if incoming + outgoing > reply.reserved_tokens:
            # Never underreport actual billable usage from a non-conforming service.
            log.warning("llm_reported_usage_exceeds_hold reply_id=%s", reply.pk)
        if incoming or outgoing:
            account.tokens_used += min(incoming + outgoing, reply.reserved_tokens)
            account.save(update_fields=["tokens_used"])
            ledger, _ = ModelUsage.objects.get_or_create(
                user_id=user_id, model_id=reply.model_id
            )
            ledger.input_tokens += incoming
            ledger.output_tokens += outgoing
            ledger.save(update_fields=["input_tokens", "output_tokens"])
        reply.status = status
        reply.content = text
        reply.input_tokens = incoming
        reply.output_tokens = outgoing
        reply.usage_source = source
        reply.error = error[:240]
        reply.reserved_tokens = 0
        reply.save(
            update_fields=[
                "status",
                "content",
                "input_tokens",
                "output_tokens",
                "usage_source",
                "error",
                "reserved_tokens",
            ]
        )
        _close_turn_if_done(turn)
        return status
