"""All monetary amounts are integral rials. Writers lock Account before any reply or ledger row."""

import logging
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from .models import Account, BillingPolicy, CreditTransaction

MAX_CREDIT = 10**15
MAX_PRICE = 10**12
log = logging.getLogger(__name__)


def toman(rial):
    return Decimal(rial) / 10 if rial is not None else None


def rial(value, maximum=MAX_CREDIT):
    try:
        value = Decimal(str(value))
        if (
            not value.is_finite()
            or value < 0
            or value > toman(maximum)
            or value.as_tuple().exponent < -1
        ):
            raise InvalidOperation
        amount = value * 10
    except (InvalidOperation, ValueError):
        raise ValidationError(
            "مبلغ معتبر را با حداکثر یک رقم اعشار وارد کنید."
        ) from None
    if (
        not amount.is_finite()
        or amount != amount.to_integral_value()
        or not 0 <= amount <= maximum
    ):
        raise ValidationError("مبلغ باید نامنفی و با دقت حداکثر یک ریال باشد.")
    return int(amount)


def calculate_cost(incoming, outgoing, input_price, output_price):
    if (
        any(
            type(n) is not int or n < 0
            for n in (incoming, outgoing, input_price, output_price)
        )
        or max(input_price, output_price) > MAX_PRICE
    ):
        raise ValidationError("تعرفهٔ معتبر ورودی و خروجی برای مدل تعیین کنید.")
    return (incoming * input_price + outgoing * output_price + 999999) // 1000000


def balance(account):
    remaining = account.credit_limit_rial - account.credit_used_rial
    return {
        "credit_limit_rial": account.credit_limit_rial,
        "credit_used_rial": account.credit_used_rial,
        "credit_remaining_rial": remaining,
        "credit_reserved_rial": account.credit_reserved_rial,
        "credit_available_rial": remaining - account.credit_reserved_rial,
        "credit_version": account.credit_version,
        "currency": "IRR",
    }


def locked_account(user_id):
    return Account.objects.select_for_update().get(user_id=user_id)


def save_balance(account):
    account.credit_version += 1
    account.save(
        update_fields=[
            "credit_limit_rial",
            "credit_used_rial",
            "credit_reserved_rial",
            "credit_version",
        ]
    )


@transaction.atomic
def change_credit(
    user_id, operation, amount, reference, reason, actor=None, refund_of=None
):
    if (
        type(amount) is not int
        or not 0 <= amount <= MAX_CREDIT
        or not reason.strip()
        or len(reason) > 240
    ):
        raise ValidationError("مبلغ یا دلیل تغییر اعتبار معتبر نیست.")
    if (
        not reference
        or len(str(reference)) > 64
        or (operation != "refund" and refund_of is not None)
    ):
        raise ValidationError("مرجع عملیات معتبر نیست.")
    account = locked_account(user_id)
    key = f"credit:{user_id}:{reference}"
    previous = CreditTransaction.objects.filter(reference=key).first()
    if previous:
        # Reject reuse with a different intent, including a stale absolute 'set'.
        if (
            previous.operation,
            previous.requested_rial,
            previous.refund_of_id,
            previous.description,
        ) != (operation, amount, refund_of, reason):
            raise ValidationError("شناسهٔ عملیات قبلاً برای تغییر دیگری استفاده شده است.")
        return previous
    kind = operation
    model_id = None
    if operation == "refund":
        original = CreditTransaction.objects.filter(
            pk=refund_of, user_id=user_id, kind="usage"
        ).first()
        refunded = (
            CreditTransaction.objects.filter(
                refund_of_id=refund_of, kind="refund"
            ).aggregate(n=Sum("amount_rial"))["n"]
            or 0
        )
        if not original or not 0 < amount <= -original.amount_rial - refunded:
            raise ValidationError("بازپرداخت از مبلغ قابل استرداد این مصرف بیشتر است.")
        delta = amount
        model_id = original.model_id
        account.credit_used_rial -= amount
    else:
        if operation in ("grant", "migration"):
            delta = amount
        elif operation in ("set", "decrease"):
            delta = (
                amount - account.credit_limit_rial if operation == "set" else -amount
            )
            kind = "adjustment"
        else:
            raise ValidationError("عملیات مالی نامعتبر است.")
        account.credit_limit_rial += delta
    if (
        account.credit_limit_rial > MAX_CREDIT
        or balance(account)["credit_available_rial"] < 0
    ):
        raise ValidationError("تغییر اعتبار با مصرف یا رزروهای فعال سازگار نیست.")
    save_balance(account)
    return CreditTransaction.objects.create(
        user_id=user_id,
        kind=kind,
        operation=operation,
        requested_rial=amount,
        amount_rial=delta,
        reference=key,
        created_by=actor,
        model_id=model_id,
        description=reason,
        refund_of_id=refund_of,
        balance_after_rial=balance(account)["credit_remaining_rial"],
    )


def initialize_account(user_id, using, initial=None):
    with transaction.atomic(using=using):
        account, created = Account.objects.using(using).get_or_create(user_id=user_id)
        if created:
            amount = (
                BillingPolicy.objects.using(using)
                .values_list("default_credit_rial", flat=True)
                .first()
            )
            amount, reason, actor = initial or (
                amount,
                "اعتبار پیش‌فرض هنگام ایجاد حساب",
                None,
            )
            if amount:
                change_credit(user_id, "grant", amount, "initial", reason, actor)


def settle(account, turn, reply, counts, source, accounted):
    """Caller holds account/turn locks inside the terminal state transaction."""
    ip, op = reply.input_price_snapshot_rial, reply.output_price_snapshot_rial
    if ip is None or op is None:  # Legacy in-flight row at upgrade.
        return
    incoming, outgoing = counts.incoming, counts.outgoing
    unsplit = accounted - (incoming or 0) - (outgoing or 0)
    calculated = None
    if source != "unknown":
        # Bill unclassified tokens at the lower rate. A known reasoning subset is output.
        known_output = (counts.reasoning or 0) if outgoing is None else 0
        rest = max(0, unsplit - known_output)
        effective_in = (incoming or 0) + (rest if ip <= op else 0)
        effective_out = (outgoing or 0) + known_output + (rest if ip > op else 0)
        calculated = calculate_cost(effective_in, effective_out, ip, op)
        if unsplit or (source == "reported" and counts.total and incoming is None):
            source = "partial"
    hold = reply.reserved_credit_rial
    charge = min(calculated or 0, hold)
    excess = (calculated or 0) - charge
    if excess:
        log.warning(
            "billing_hold_exceeded reply_id=%s uncovered_rial=%s", reply.pk, excess
        )
    account.credit_reserved_rial -= hold
    account.credit_used_rial += charge
    save_balance(account)
    reply.reserved_credit_rial = 0
    reply.cost_rial = charge if calculated is not None else None
    reply.billing_status = "settled" if calculated is not None else "review"
    reply.billing_source = source
    return CreditTransaction.objects.create(
        user_id=account.user_id,
        model_id=reply.model_id,
        kind="usage",
        reference=f"reply:{reply.pk}",
        reply_id=reply.pk,
        request_id=turn.request_id,
        amount_rial=-charge,
        balance_after_rial=balance(account)["credit_remaining_rial"],
        status=reply.status,
        source=source,
        input_price=ip,
        output_price=op,
        reserved_rial=hold,
        calculated_rial=calculated,
        uncovered_rial=excess,
        input_tokens=incoming,
        output_tokens=outgoing,
        reasoning_tokens=counts.reasoning,
        total_tokens=counts.total,
        unsplit_tokens=unsplit,
    )
