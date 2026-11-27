"""Bounded financial reports over durable postings. Browsing never reads chat text."""

import csv
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import (
    Count,
    Sum,
    Avg,
    Max,
    Q,
    F,
    Value,
    BigIntegerField,
    DecimalField,
)
from django.db.models.functions import Coalesce, TruncDate, TruncWeek, TruncMonth
from django.core.handlers.asgi import ASGIRequest
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import CreditTransaction, Account, LanguageModel
from .permissions import IsPortalAdmin
from .billing import balance, toman

LABELS = {
    "user_id": "شناسه کاربر",
    "user__username": "کاربر",
    "model_id": "شناسه مدل",
    "model__name": "مدل",
    "model__provider": "سرویس",
    "model__connection__name": "اتصال",
    "requests": "درخواست",
    "completed": "موفق",
    "failed": "ناموفق",
    "cancelled": "متوقف",
    "cost_rial": "هزینه (تومان)",
    "calculated_rial_sum": "محاسبه‌شده (تومان)",
    "uncovered": "پوشش‌نداده (تومان)",
    "inputs": "توکن ورودی",
    "outputs": "توکن خروجی",
    "reasoning": "توکن استدلال",
    "tokens": "کل توکن",
    "unsplit": "توکن تفکیک‌نشده",
    "average_rial": "میانگین (تومان)",
    "last": "آخرین مصرف",
    "amount_rial": "مبلغ (تومان)",
    "created_at": "تاریخ",
    "kind": "نوع",
    "balance_after_rial": "مانده (تومان)",
    "source": "منبع",
    "status": "وضعیت",
    "description": "دلیل",
    "created_by__username": "عامل",
    "id": "ردیف",
    "period": "دوره",
    "users": "تعداد کاربران",
    "models": "تعداد مدل",
    "reference": "مرجع",
    "request_id": "شناسه درخواست",
    "reply_id": "شناسه پاسخ",
    "review": "نیازمند بررسی",
    "share": "درصد مصرف کاربر",
    "refund_rial": "بازپرداخت (تومان)",
    "adjustment_rial": "اصلاح (تومان)",
}
LABELS.update(
    {
        "user__account__credit_limit_rial": "اعتبار کل (تومان)",
        "user__account__credit_used_rial": "مصرف خالص (تومان)",
        "user__account__credit_reserved_rial": "رزرو (تومان)",
    }
)
KIND = {
    "grant": "افزایش اعتبار",
    "usage": "مصرف",
    "refund": "بازپرداخت",
    "migration": "اعتبار اولیه",
    "adjustment": "اصلاح",
}
MONEY = {
    "cost_rial",
    "balance_after_rial",
    "amount_rial",
    "average_rial",
    "calculated_rial_sum",
    "uncovered",
    "refund_rial",
    "adjustment_rial",
}


def number_param(params, key, default=None, maximum=2**31 - 1):
    raw = params.get(key)
    if not raw:
        return default
    if (
        not raw.isascii()
        or not raw.isdecimal()
        or len(raw) > 12
        or not 1 <= int(raw) <= maximum
    ):
        raise ValidationError("پارامتر عددی گزارش نامعتبر است.")
    return int(raw)


def filtered(request, admin, skip_model=False):
    params = request.query_params
    rows = (
        CreditTransaction.objects.all()
        if admin
        else CreditTransaction.objects.filter(user=request.user)
    )
    for key, field in [
        ("model", "model_id"),
        *(
            [("user", "user_id"), ("connection", "model__connection_id")]
            if admin
            else []
        ),
    ]:
        val = number_param(params, key)
        if val and not (skip_model and key == "model"):
            rows = rows.filter(**{field: val})
    if admin and params.get("q"):
        rows = rows.filter(user__username__icontains=params["q"][:150])
    if admin and params.get("provider"):
        rows = rows.filter(model__provider=params["provider"][:20])
    for key in ("status", "source", "kind"):
        if params.get(key):
            rows = rows.filter(**{key: params[key][:16]})
    try:
        start = date.fromisoformat(params["from"]) if params.get("from") else None
        end = date.fromisoformat(params["to"]) if params.get("to") else None
        if start and end and start > end:
            raise ValueError
        if start:
            rows = rows.filter(
                created_at__gte=timezone.make_aware(datetime.combine(start, time.min))
            )
        if end and end < date.max:
            rows = rows.filter(
                created_at__lt=timezone.make_aware(
                    datetime.combine(end + timedelta(days=1), time.min)
                )
            )
    except (ValueError, OverflowError):
        raise ValidationError("بازهٔ تاریخ گزارش معتبر نیست.") from None
    return rows


def summation(field):
    return Coalesce(Sum(field), Value(0), output_field=BigIntegerField())


def metrics(admin):
    data = dict(
        requests=Count("id"),
        cost_rial=-summation("amount_rial"),
        average_rial=-Avg(
            "amount_rial", output_field=DecimalField(max_digits=30, decimal_places=2)
        ),
        last=Max("created_at"),
        review=Count("id", filter=Q(calculated_rial__isnull=True)),
    )
    if admin:
        data.update(
            completed=Count("id", filter=Q(status="completed")),
            failed=Count("id", filter=Q(status="failed")),
            cancelled=Count("id", filter=Q(status="cancelled")),
            inputs=summation("input_tokens"),
            outputs=summation("output_tokens"),
            reasoning=summation("reasoning_tokens"),
            unsplit=summation("unsplit_tokens"),
            tokens=summation("input_tokens")
            + summation("output_tokens")
            + summation("unsplit_tokens"),
            calculated_rial_sum=summation("calculated_rial"),
            uncovered=summation("uncovered_rial"),
        )
    return data


class Echo:
    def write(self, value):
        return value


def export(rows, fields, request):
    writer = csv.writer(Echo())

    header = "\ufeff" + writer.writerow([LABELS.get(f, f) for f in fields])

    def line(row):
        values = []
        for field in fields:
            value = row[field]
            if (field in MONEY or field.endswith("_rial")) and value is not None:
                value = toman(str(value))
            elif isinstance(value, str) and value.lstrip().startswith(
                ("=", "+", "-", "@")
            ):
                value = "'" + value
            values.append(value)
        return writer.writerow(values)

    def lines():
        yield header
        for row in rows.iterator(chunk_size=500):
            yield line(row)

    async def async_lines():
        yield header
        async for row in rows.aiterator(chunk_size=500):
            yield line(row)

    return StreamingHttpResponse(
        async_lines()
        if isinstance(getattr(request, "_request", request), ASGIRequest)
        else lines(),
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="billing.csv"'},
    )


def report(request, view, admin):
    rows = filtered(request, admin)
    params = request.query_params
    if view == "transactions":
        fields = [
            "id",
            "created_at",
            "kind",
            "model__name",
            "amount_rial",
            "balance_after_rial",
            "source",
            "status",
            "reference",
        ]
        if admin:
            fields += [
                "user__username",
                "created_by__username",
                "description",
                "request_id",
                "reply_id",
            ]
        order = params.get("sort", "-created_at")
        if order.removeprefix("-") not in {"created_at", "amount_rial", "kind", "id"}:
            raise ValidationError("ترتیب گزارش معتبر نیست.")
        table = rows.values(*fields).order_by(order, "-id")
        totals = rows.aggregate(
            net=summation("amount_rial"),
            refund_rial=Coalesce(
                Sum("amount_rial", filter=Q(kind="refund")),
                0,
                output_field=BigIntegerField(),
            ),
            adjustment_rial=Coalesce(
                Sum("amount_rial", filter=Q(kind="adjustment")),
                0,
                output_field=BigIntegerField(),
            ),
        )
        totals["amount_rial"] = totals.pop("net")
    else:
        usage = rows.filter(kind="usage")
        group = {
            "users": [
                "user_id",
                "user__username",
                "user__account__credit_limit_rial",
                "user__account__credit_used_rial",
                "user__account__credit_reserved_rial",
            ],
            "models": ["model_id", "model__name"],
            "user-model-usage": [
                "user_id",
                "user__username",
                "model_id",
                "model__name",
                "model__provider",
                "model__connection__name",
            ],
            "usage": ["model_id", "model__name"],
            "trend": ["period"],
        }
        if view not in group:
            raise ValidationError("نمای گزارش معتبر نیست.")
        if view == "trend":
            truncate = {"day": TruncDate, "week": TruncWeek, "month": TruncMonth}.get(
                params.get("interval", "day")
            )
            if not truncate:
                raise ValidationError("دوره معتبر نیست.")
            usage = usage.annotate(period=truncate("created_at"))
        aggregate = metrics(admin)
        if view == "models":
            aggregate["users"] = Count("user_id", distinct=True)
        if view == "users":
            aggregate["models"] = Count("model_id", distinct=True)
        fields = [*group[view], *aggregate]
        order = params.get("sort", "-period" if view == "trend" else "-cost_rial")
        if order.removeprefix("-") not in fields:
            raise ValidationError("ترتیب گزارش معتبر نیست.")
        table = (
            usage.values(*group[view])
            .annotate(**aggregate)
            .order_by(order, *group[view])
        )
        totals = usage.aggregate(**metrics(admin))
    if params.get("export") == "csv":
        return export(table, fields, request)
    page = number_param(params, "page", 1)
    size = number_param(params, "size", 25, 100)
    result = list(table[(page - 1) * size : page * size])
    if view in ("usage", "user-model-usage"):
        # Fetch denominators once per page. Include other models under the same time filters.
        owners = {row.get("user_id", request.user.pk) for row in result}
        all_models = filtered(request, admin, skip_model=True).filter(
            kind="usage", user_id__in=owners
        )
        spent = dict(
            all_models.values("user_id")
            .annotate(n=-Sum("amount_rial"))
            .values_list("user_id", "n")
        )
        for row in result:
            total = spent.get(row.get("user_id", request.user.pk))
            row["share"] = (
                round(Decimal(row["cost_rial"]) * 100 / total, 1) if total else 0
            )
    return Response(
        {
            "results": result,
            "count": table.count(),
            "page": page,
            "size": size,
            "totals": totals,
        }
    )


@api_view(["GET"])
def personal_report(request, view):
    if view not in ("transactions", "usage", "trend"):
        raise ValidationError("نمای گزارش معتبر نیست.")
    return report(request, view, False)


@api_view(["GET"])
@permission_classes([IsPortalAdmin])
def admin_report(request, view):
    if view != "summary":
        return report(request, view, True)
    accounts = Account.objects.annotate(
        available=F("credit_limit_rial")
        - F("credit_used_rial")
        - F("credit_reserved_rial")
    )
    summary = accounts.aggregate(
        allocated=summation("credit_limit_rial"),
        used=summation("credit_used_rial"),
        reserved=summation("credit_reserved_rial"),
        active=Count("pk", filter=Q(user__is_active=True)),
        empty=Count("pk", filter=Q(available=0)),
        low=Count(
            "pk", filter=Q(available__gt=0, available__lte=F("credit_limit_rial") / 10)
        ),
    )
    summary["remaining"] = summary["allocated"] - summary["used"]
    usage = CreditTransaction.objects.filter(kind="usage")
    today = timezone.localdate()
    for days in (1, 7, 30):
        summary[f"cost_{days}d"] = usage.filter(
            created_at__date__gte=today - timedelta(days=days - 1)
        ).aggregate(n=-summation("amount_rial"))["n"]
    summary.update(
        usage.aggregate(
            uncovered=summation("uncovered_rial"),
            unknown=Count("pk", filter=Q(source="unknown")),
            estimated=Count(
                "pk",
                filter=Q(
                    source__in=["estimated", "estimate_in", "estimate_out", "partial"]
                ),
            ),
        )
    )
    summary["unpriced"] = LanguageModel.objects.filter(
        Q(input_price_per_million_rial__isnull=True)
        | Q(output_price_per_million_rial__isnull=True)
    ).count()
    summary["highest_prices"] = list(
        LanguageModel.objects.exclude(output_price_per_million_rial=None)
        .order_by("-output_price_per_million_rial", "pk")
        .values("id", "name", "output_price_per_million_rial")[:5]
    )
    uid = number_param(request.query_params, "user")
    if uid:
        selected = accounts.filter(user_id=uid).first()
        summary["account"] = balance(selected) if selected else None
    return Response(summary)
