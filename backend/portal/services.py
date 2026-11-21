"""Reserve, call and settle are separate operations. No provider I/O inside atomic()."""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as ConfigurationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from .branches import BranchState, RequestConflict, UNSPECIFIED
from .models import Account, Conversation, LanguageModel, Message, ModelUsage
from .capabilities import runtime_model, validate_reasoning_overrides
from .thinking import validate_capabilities
from .reasoning_profiles import legacy_selection
from .tokens import Usage, input_counter

log = logging.getLogger(__name__)
LEASE = timedelta(seconds=120)
TURN_DEADLINE = timedelta(minutes=10)
EXPIRED = "مهلت درخواست به پایان رسید. دوباره تلاش کنید."


@dataclass
class Job:
    reply: Message
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
            input_tokens=None,
            output_tokens=None,
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
        conversation__user__is_active=True,
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


def _origin(model):
    # Bind preserved reasoning to the exact configured service and upstream model.
    if model.reasoning_policy != "preserve":
        return ""
    target = (model.connection_id, model.connection.base_url, model.model_id)
    return hashlib.sha256(repr(target).encode()).hexdigest()


def _admission_plan(chat, models, content, thinking, reasoning, history_ids):
    plans = []
    for configured in models:
        try:
            validate_capabilities(configured)
            validate_reasoning_overrides(configured)
            model = runtime_model(configured)
            if not model.can_chat:
                raise ValidationError("این مدل از تولید متن پشتیبانی نمی‌کند.")
            if (
                model.reasoning_profile.wire == "kimi_preserved"
                and model.reasoning_policy != "preserve"
            ):
                raise ConfigurationError("سیاست تاریخچهٔ Kimi معتبر نیست.")
        except ConfigurationError:
            raise ValidationError(
                "تنظیمات Thinking یا سقف خروجی مدل معتبر نیست."
            ) from None
        key = str(model.pk)
        level = thinking.get(key, model.thinking_default)
        profile = model.reasoning_profile
        try:
            if key in reasoning:
                settings = reasoning[key]
                level = ""
            elif key in thinking or (
                level and not model.auto_thinking and not model.reasoning_overrides
            ):
                settings = legacy_selection(model, level)
            else:
                settings = profile.defaults()
            profile.payload(settings)
        except ConfigurationError as exc:
            raise ValidationError(exc.messages) from None
        if model.reasoning_policy == "preserve" and model.connection is None:
            raise ValidationError("تنظیمات اتصال مدل کامل نیست.")
        origin = _origin(model)
        count = input_counter(model.tokenizer_name)
        messages = []
        bound = model.framing_tokens
        available = model.context_window - model.max_output_tokens
        prior = chat.messages.filter(
            role="assistant", status="completed", model=model, parent_id__in=history_ids
        ).order_by("id")
        fields = ["parent__content", "content"]
        if origin:
            fields += ["reasoning_origin", "reasoning_content"]
        for question, answer, *preserved in prior.values_list(*fields).iterator(
            chunk_size=16
        ):
            assistant = {"role": "assistant", "content": answer}
            if origin:
                if preserved[0] != origin:
                    raise ValidationError(
                        "برای حفظ تاریخچهٔ کامل استدلال این مدل، گفتگوی تازه بسازید."
                    )
                if preserved[1] is not None:
                    assistant["reasoning_content"] = preserved[1]
            messages.extend([{"role": "user", "content": question}, assistant])
            bound += (
                2 * model.framing_tokens
                + count(question)
                + count(answer)
                + count(assistant.get("reasoning_content", ""))
            )
            if bound > available:
                raise ValidationError(
                    "ظرفیت تاریخچهٔ مدل تکمیل شده است؛ گفتگوی تازه بسازید."
                )
        messages.append({"role": "user", "content": content})
        bound += count(content) + model.framing_tokens
        hold = bound + model.max_output_tokens
        if hold > model.context_window or model.max_output_tokens < 1:
            raise ValidationError(
                "ظرفیت گفتگو برای مدل انتخابی کافی نیست؛ گفتگوی تازه بسازید."
            )
        plans.append((model, messages, bound, hold, level, origin, settings))
    return plans


def reserve_turn(
    user,
    conversation,
    content,
    model_ids=None,
    request_id=None,
    thinking=None,
    reasoning=None,
    edit_of=None,
    expected_leaf=UNSPECIFIED,
):
    with transaction.atomic():
        account = _locked_account(user.pk)
        if not get_user_model().objects.filter(pk=user.pk, is_active=True).exists():
            raise PermissionDenied("این حساب غیرفعال است.")
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
        branch = BranchState(chat)
        branch.check_leaf(expected_leaf)
        history_ids = branch.path
        if edit_of is not None:
            history_ids = branch.prefix(edit_of)
            replies = list(
                chat.messages.filter(parent_id=edit_of, role="assistant")
                .only("model_id", "thinking_level", "reasoning_settings")
                .order_by("pk")
            )
            if model_ids is None:
                model_ids = [r.model_id for r in replies if r.model_id is not None]
            thinking, reasoning = dict(thinking or {}), dict(reasoning or {})
            for r in replies:
                key = str(r.model_id)
                if (
                    r.model_id in model_ids
                    and key not in reasoning
                    and key not in thinking
                ):
                    if r.thinking_level and not r.reasoning_settings:
                        thinking[key] = r.thinking_level
                    else:
                        reasoning[key] = r.reasoning_settings
        if model_ids is None:
            raise ValidationError("مدل‌های این درخواست را انتخاب کنید.")
        thinking = {} if thinking is None else thinking
        if not isinstance(thinking, dict) or set(thinking) - {
            str(pk) for pk in model_ids
        }:
            raise ValidationError("تنظیم Thinking فقط برای مدل‌های انتخاب‌شده مجاز است.")
        reasoning = {} if reasoning is None else reasoning
        if (
            not isinstance(reasoning, dict)
            or set(reasoning) - {str(pk) for pk in model_ids}
            or set(reasoning).intersection(thinking)
        ):
            raise ValidationError(
                "تنظیم استدلال باید برای هر مدل انتخاب‌شده فقط یک‌بار ارسال شود."
            )
        if not 1 <= len(model_ids) <= 3 or len(set(model_ids)) != len(model_ids):
            raise ValidationError("یک تا سه مدل متفاوت انتخاب کنید.")
        models = list(
            LanguageModel.objects.filter(pk__in=model_ids, enabled=True)
            .select_related("connection")
            .order_by("id")
        )
        if len(models) != len(model_ids):
            raise ValidationError("یکی از مدل‌ها موجود یا فعال نیست.")
        plans = _admission_plan(chat, models, content, thinking, reasoning, history_ids)
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
        if edit_of is not None:
            chat.messages.filter(pk=edit_of).update(selected_version=False)
        turn = Message.objects.create(
            previous_turn_id=history_ids[-1] if history_ids else None,
            selected_version=True,
            conversation=chat,
            role="user",
            content=content,
            status="running",
            request_id=request_id or uuid.uuid4(),
            lease_until=timezone.now() + LEASE,
        )
        jobs = []
        for model, messages, bound, hold, level, origin, settings in plans:
            reply = Message.objects.create(
                conversation=chat,
                role="assistant",
                model=model,
                parent=turn,
                status="running",
                input_bound=bound,
                reserved_tokens=hold,
                thinking_level=level,
                reasoning_settings=settings,
                reasoning_origin=origin,
            )
            jobs.append(Job(reply, model, messages))
        return turn, jobs


@transaction.atomic
def select_version(user, conversation, anchor, target, expected_leaf):
    _locked_account(user.pk)
    _expire_locked(user.pk, timezone.now())
    chat = get_object_or_404(
        Conversation.objects.select_for_update(),
        user=user,
        pk=conversation.pk,
        created_at__gte=timezone.now() - timedelta(days=30),
    )
    if chat.messages.filter(role="user", status="running").exists():
        raise RequestConflict("تا پایان پاسخ یا توقف آن، تغییر نسخه ممکن نیست.")
    branch = BranchState(chat)
    branch.check_leaf(expected_leaf)
    branch.prefix(anchor)
    if target not in branch.versions(anchor):
        raise NotFound("نسخهٔ انتخاب‌شده متعلق به این نوبت نیست.")
    if anchor != target:
        chat.messages.filter(pk=anchor).update(selected_version=False)
        chat.messages.filter(pk=target).update(selected_version=True)


def _usage(reply, text, reasoning_bytes, usage):
    if isinstance(usage, tuple):
        incoming, outgoing = usage
        usage = Usage(incoming, outgoing, incoming + outgoing)
    if usage is not None and usage.total is not None:
        return usage, "reported"
    if not text and not reasoning_bytes:
        return (usage, "partial") if usage else (Usage(None, None, None), "unknown")
    # When only one side was reported, estimate only the missing side.
    usage = usage or Usage(None, None, None)
    incoming = reply.input_bound if usage.incoming is None else usage.incoming
    outgoing = usage.outgoing
    source = "estimate_in"
    if outgoing is None:
        reasoning_estimate = (
            reasoning_bytes if usage.reasoning is None else usage.reasoning
        )
        size = len(text.encode()) + reasoning_estimate
        outgoing = max(
            usage.reasoning or 0, min(reply.reserved_tokens - reply.input_bound, size)
        )
        source = "estimated" if usage.incoming is None else "estimate_out"
    return Usage(incoming, outgoing, incoming + outgoing, usage.reasoning), source


def finish_reply(
    reply_id,
    status,
    text="",
    usage=None,
    error="",
    reasoning=None,
    reasoning_bytes=0,
    *,
    finished_at=None,
):
    finished_at = finished_at or timezone.now()
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
            return "cancelled", None  # Owner removed after the lease was recovered.
        account = _locked_account(user_id)
        turn = Message.objects.select_for_update().filter(pk=parent_id).first()
        if turn is None:
            return "cancelled", None
        reply = Message.objects.get(pk=reply_id)
        if reply.status != "running":
            return reply.status, reply.response_duration_ms  # Fence late writers.
        if turn.cancel_requested or status == "cancelled":
            status = "cancelled"
            if not turn.cancel_requested:
                turn.cancel_requested = True
                turn.save(update_fields=["cancel_requested"])
        counts, source = _usage(reply, text, reasoning_bytes, usage)
        # With no total or visible text, only the reported lower bound is chargeable.
        accounted = counts.total
        if accounted is None:
            accounted = (counts.incoming or 0) + (
                counts.outgoing or counts.reasoning or 0
            )
        if accounted > reply.reserved_tokens:
            # Never underreport actual billable usage from a non-conforming service.
            log.warning("llm_reported_usage_exceeds_hold reply_id=%s", reply.pk)
        if accounted:
            account.tokens_used += min(accounted, reply.reserved_tokens)
            account.save(update_fields=["tokens_used"])
            ledger, _ = ModelUsage.objects.get_or_create(
                user_id=user_id, model_id=reply.model_id
            )
            ledger.input_tokens += counts.incoming or 0
            ledger.output_tokens += counts.outgoing or 0
            ledger.unsplit_tokens += (
                accounted - (counts.incoming or 0) - (counts.outgoing or 0)
            )
            ledger.save(
                update_fields=["input_tokens", "output_tokens", "unsplit_tokens"]
            )
        reply.response_duration_ms = reply.elapsed_ms(finished_at)
        reply.status = status
        reply.content = text
        reply.input_tokens = counts.incoming
        reply.output_tokens = counts.outgoing
        reply.total_tokens = counts.total
        reply.reasoning_tokens = counts.reasoning
        reply.reasoning_content = reasoning
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
                "total_tokens",
                "reasoning_tokens",
                "reasoning_content",
                "error",
                "reserved_tokens",
                "response_duration_ms",
            ]
        )
        _close_turn_if_done(turn)
        return status, reply.response_duration_ms
