from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Q, Count

from portal import billing
from portal.models import Account, CreditTransaction, LanguageModel, Message, ModelUsage


class Command(BaseCommand):
    help = "Audit balances, holds and lifetime aggregates; optionally grant migration credit exactly once per user."

    def add_arguments(self, parser):
        parser.add_argument("--user", type=int)
        parser.add_argument(
            "--initial-toman", help="Initial migration grant; defaults to dry run."
        )
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        missing = LanguageModel.objects.filter(
            Q(input_price_per_million_rial=None) | Q(output_price_per_million_rial=None)
        )
        for pk, name in missing.values_list("pk", "name").iterator():
            self.stdout.write(f"Unpriced model {pk}: {name}")
        accounts = Account.objects.all()
        if options["user"] is not None:
            accounts = accounts.filter(user_id=options["user"])
            if not accounts.exists():
                raise CommandError("Unknown account")
        amount = None
        if options["initial_toman"] is not None:
            try:
                amount = billing.rial(options["initial_toman"])
            except ValidationError as exc:
                raise CommandError(str(exc)) from None
        failures = 0
        for uid in (
            accounts.order_by("user_id").values_list("user_id", flat=True).iterator()
        ):
            with transaction.atomic():
                account = billing.locked_account(uid)
                entries = CreditTransaction.objects.filter(user_id=uid)
                net = entries.aggregate(
                    funded=Sum(
                        "amount_rial",
                        filter=Q(kind__in=["grant", "adjustment", "migration"]),
                    ),
                    spent=Sum("amount_rial", filter=Q(kind__in=["usage", "refund"])),
                )
                holds = (
                    Message.objects.filter(
                        conversation__user_id=uid, status="running", role="assistant"
                    ).aggregate(n=Sum("reserved_credit_rial"))["n"]
                    or 0
                )
                sums = {
                    model: (-value, count)
                    for model, value, count in entries.filter(kind="usage")
                    .values("model_id")
                    .annotate(n=Sum("amount_rial"), c=Count("pk"))
                    .values_list("model_id", "n", "c")
                }
                aggregates = {
                    model: (value, count)
                    for model, value, count in ModelUsage.objects.filter(
                        user_id=uid, billed_requests__gt=0
                    ).values_list("model_id", "billed_rial", "billed_requests")
                }
                if ((net["funded"] or 0), -(net["spent"] or 0), holds) != (
                    account.credit_limit_rial,
                    account.credit_used_rial,
                    account.credit_reserved_rial,
                ) or sums != aggregates:
                    self.stderr.write(f"Mismatch user_id={uid}")
                    failures += 1
                    continue
                if (
                    amount
                    and not entries.filter(
                        kind__in=["migration", "grant", "adjustment"]
                    ).exists()
                ):
                    self.stdout.write(
                        f"Initial credit user_id={uid} toman={billing.toman(amount)} apply={options['apply']}"
                    )
                    if options["apply"]:
                        billing.change_credit(
                            uid,
                            "migration",
                            amount,
                            "migration-initial",
                            "تخصیص اولیه هنگام مهاجرت",
                        )
        if failures:
            raise CommandError(f"{failures} account(s) require review")
        self.stdout.write("Account, reservation, ledger and usage totals reconcile.")
