from datetime import timedelta
from decimal import Decimal
from io import StringIO
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError as InvalidRequest

from . import billing
from .models import (
    Account,
    BillingPolicy,
    Conversation,
    CreditTransaction,
    LanguageModel,
    Message,
    ModelUsage,
)
from .services import reserve_turn, finish_reply, recover_reservations
from .tokens import Usage


class BillingTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("buyer")
        self.admin = User.objects.create_superuser("manager")
        self.chat = Conversation.objects.create(user=self.owner, title="private")
        self.models = [
            LanguageModel.objects.create(
                name=n,
                provider="demo",
                model_id=n,
                max_output_tokens=1400,
                input_price_per_million_rial=i,
                output_price_per_million_rial=o,
            )
            for n, i, o in [("A", 1500000, 12000000), ("B", 400000, 1600000)]
        ]
        self.ids = [m.pk for m in self.models]
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def account(self):
        return Account.objects.get(user=self.owner)

    def credit(self, op, amount, **kwargs):
        return billing.change_credit(
            self.owner.pk,
            op,
            amount,
            kwargs.pop("reference", str(uuid4())),
            "test",
            self.admin,
            **kwargs,
        )

    def reserve(self):
        return reserve_turn(self.owner, self.chat, "x" * 2000, self.ids)

    def acceptance(self):
        self.credit("grant", 5000000)
        turn, jobs = self.reserve()
        held = self.account().credit_reserved_rial
        self.assertEqual(held, sum(j.reply.reserved_credit_rial for j in jobs))
        LanguageModel.objects.filter(pk=self.ids[0]).update(
            output_price_per_million_rial=0
        )
        for j in jobs:
            finish_reply(
                j.reply.pk, "completed", "answer", Usage(2000, 1000, 3000, 600)
            )
            finish_reply(j.reply.pk, "completed", "duplicate", (6000, 6000))
        return turn, jobs

    def test_exact_acceptance_retention_and_reconciliation(self):
        turn, jobs = self.acceptance()
        self.assertEqual(
            list(turn.replies.order_by("pk").values_list("cost_rial", flat=True)),
            [15000, 2400],
        )
        a = billing.balance(self.account())
        self.assertEqual(
            (
                a["credit_used_rial"],
                a["credit_available_rial"],
                a["credit_reserved_rial"],
            ),
            (17400, 4982600, 0),
        )
        Conversation.objects.filter(pk=self.chat.pk).update(
            created_at=timezone.now() - timedelta(days=31)
        )
        call_command("purge_history", stdout=StringIO())
        self.assertFalse(Message.objects.exists())
        self.assertEqual(CreditTransaction.objects.count(), 3)
        self.assertEqual(
            list(
                ModelUsage.objects.order_by("model_id").values_list(
                    "billed_rial", flat=True
                )
            ),
            [15000, 2400],
        )
        call_command("audit_billing", stdout=StringIO())
        entry = self.owner.credit_entries.first()
        with self.assertRaises(ValidationError):
            entry.delete()
        with self.assertRaises(ValidationError):
            self.owner.credit_entries.update(amount_rial=8)
        with self.assertRaises(ProtectedError):
            self.owner.delete()

    def test_money_and_rounding(self):
        self.assertEqual(billing.calculate_cost(2000, 1000, 1500000, 12000000), 15000)
        self.assertEqual(billing.calculate_cost(1, 1, 1, 1), 1)
        self.assertEqual(billing.calculate_cost(123, 456, 0, 0), 0)
        self.assertEqual(billing.toman(1), Decimal("0.1"))
        self.assertEqual(billing.rial("0.1"), 1)
        for invalid in ("a", "-1", "0.03", "NaN", "1e100"):
            with self.assertRaises(ValidationError):
                billing.rial(invalid)

    def test_admission_estimate_and_model_pricing(self):
        with self.assertRaises(InvalidRequest):
            self.reserve()
        self.assertFalse(Message.objects.exists())
        estimate = self.client.post(
            "/api/credits/estimate/",
            {"content": "x" * 2000, "model_ids": self.ids},
            format="json",
        )
        self.assertEqual(estimate.status_code, 200)
        self.assertGreater(estimate.data["required_rial"], 0)
        self.assertEqual(self.account().credit_version, 0)
        LanguageModel.objects.filter(pk=self.ids[0]).update(
            input_price_per_million_rial=None
        )
        with self.assertRaises(InvalidRequest):
            self.reserve()
        LanguageModel.objects.update(
            input_price_per_million_rial=0, output_price_per_million_rial=0
        )
        _, jobs = self.reserve()
        for j in jobs:
            finish_reply(j.reply.pk, "completed", "ok", (1, 1))
        self.assertEqual(self.account().credit_used_rial, 0)

    def test_refund_limits_idempotency_and_decreases(self):
        _, jobs = self.acceptance()
        use = CreditTransaction.objects.get(reply_id=jobs[0].reply.pk)
        for _ in range(2):
            self.credit("refund", 10000, reference="same", refund_of=use.pk)
        self.assertEqual(self.account().credit_used_rial, 7400)
        with self.assertRaises(ValidationError):
            self.credit("refund", 5001, refund_of=use.pk)
        self.credit("decrease", 100)
        self.reserve()
        with self.assertRaises(ValidationError):
            self.credit("set", 7400)
        call_command("audit_billing", stdout=StringIO())

    def test_incomplete_unknown_overrun_and_expiry(self):
        self.credit("grant", 5000000)
        turn, jobs = self.reserve()
        finish_reply(jobs[0].reply.pk, "cancelled", "part", Usage(None, None, 100, 20))
        e = CreditTransaction.objects.get(reply_id=jobs[0].reply.pk)
        self.assertEqual(
            (e.calculated_rial, e.source, e.status), (360, "partial", "cancelled")
        )
        Message.objects.filter(pk=turn.pk).update(
            lease_until=timezone.now() - timedelta(minutes=1)
        )
        self.assertEqual(recover_reservations(), 1)
        finish_reply(jobs[1].reply.pk, "completed", "late", (3, 3))
        e = CreditTransaction.objects.get(reply_id=jobs[1].reply.pk)
        self.assertIsNone(e.calculated_rial)
        self.assertEqual(e.source, "unknown")
        _, jobs = self.reserve()
        hold = jobs[0].reply.reserved_credit_rial
        finish_reply(jobs[0].reply.pk, "failed", usage=(200000, 200000))
        e = CreditTransaction.objects.get(reply_id=jobs[0].reply.pk)
        self.assertEqual(
            (e.amount_rial, e.uncovered_rial), (-hold, e.calculated_rial - hold)
        )
        finish_reply(jobs[1].reply.pk, "failed", usage=(0, 0))
        self.assertEqual(self.account().credit_reserved_rial, 0)

    def test_reports_filters_permissions_totals_csv_and_pagination(self):
        self.acceptance()
        self.chat.delete()
        other = User.objects.create_user("another")
        billing.change_credit(other.pk, "grant", 123, "separate", "private")
        res = self.client.get("/api/credits/transactions/report/", {"user": other.pk})
        self.assertEqual(res.data["count"], 3)
        self.assertNotIn(
            "inputs", self.client.get("/api/credits/usage/report/").data["totals"]
        )
        self.assertEqual(
            self.client.get("/api/admin/billing/summary/").status_code, 403
        )
        self.client.force_authenticate(self.admin)
        for view in ("users", "models", "trend", "transactions", "summary"):
            res = self.client.get(
                f"/api/admin/billing/{view}/", {"user": self.owner.pk}
            )
            self.assertEqual(res.status_code, 200)
        url = "/api/admin/billing/user-model-usage/"
        res = self.client.get(url, {"user": self.owner.pk, "size": 1})
        self.assertEqual((res.data["count"], len(res.data["results"])), (2, 1))
        total = res.data["totals"]
        self.assertEqual(
            (
                total["requests"],
                total["inputs"],
                total["outputs"],
                total["reasoning"],
                total["tokens"],
                total["cost_rial"],
                total["average_rial"],
            ),
            (2, 4000, 2000, 1200, 6000, 17400, 8700),
        )
        self.assertEqual(
            self.client.get(
                url, {"model": self.ids[0], "source": "reported", "status": "completed"}
            ).data["totals"]["cost_rial"],
            15000,
        )
        self.assertEqual(self.client.get(url, {"from": "2100-01-01"}).data["count"], 0)
        self.assertEqual(self.client.get(url, {"sort": "--cost_rial"}).status_code, 400)
        csv = b"".join(
            self.client.get(url, {"export": "csv"}).streaming_content
        ).decode("utf-8-sig")
        self.assertIn("1500", csv)
        self.assertIn("کاربر", csv)

    def test_defaults_and_migration_grant_are_audited(self):
        BillingPolicy.objects.create(default_credit_rial=250)
        user = User.objects.create_user("new")
        self.assertEqual(user.credit_entries.get().amount_rial, 250)
        for apply in (False, True, True):
            call_command(
                "audit_billing",
                user=self.owner.pk,
                initial_toman="10.1",
                apply=apply,
                stdout=StringIO(),
            )
            self.assertEqual(self.account().credit_limit_rial, 101 if apply else 0)
        self.assertEqual(self.owner.credit_entries.count(), 1)

    def test_admin_form_grant_role_and_guarded_bulk_changes(self):
        from django.test import Client
        from django.urls import reverse

        admin = Client()
        admin.force_login(self.admin)
        BillingPolicy.objects.create(default_credit_rial=1000)
        data = {
            "username": "onboard",
            "password1": "Strong-test-pass-192!",
            "password2": "Strong-test-pass-192!",
            "role": "user",
            "is_active": "on",
            "usable_password": "true",
            "initial_credit": "500000",
            "credit_reason": "onboarding",
        }
        result = admin.post(reverse("admin:auth_user_add"), data)
        self.assertEqual(result.status_code, 302)
        user = User.objects.get(username="onboard")
        entry = user.credit_entries.get()
        self.assertEqual(
            (entry.kind, entry.amount_rial, entry.created_by_id),
            ("grant", 5000000, self.admin.pk),
        )
        url = reverse("admin:portal_user_credit", args=[user.pk])
        data = {
            "operation": "decrease",
            "amount": "100.1",
            "reason": "correction",
            "reference": str(uuid4()),
            "confirm_credit": "1",
        }
        for _ in range(2):
            self.assertEqual(admin.post(url, data).status_code, 302)
        self.assertEqual(user.credit_entries.count(), 2)
        data.update(amount="500000", reference=str(uuid4()))
        self.assertContains(admin.post(url, data), "رزروهای فعال")
        self.assertEqual(Account.objects.get(user=user).credit_limit_rial, 4998999)
        self.assertEqual(
            admin.get(
                reverse("admin:portal_credittransaction_change", args=[entry.pk])
            ).status_code,
            200,
        )
        self.assertEqual(
            admin.post(
                reverse("admin:portal_credittransaction_change", args=[entry.pk]),
                {"amount_rial": 9},
            ).status_code,
            403,
        )
        admin.force_login(self.owner)
        self.assertEqual(admin.post(url, data).status_code, 302)
