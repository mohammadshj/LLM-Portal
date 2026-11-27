from .billing import change_credit
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from .models import Account, Conversation, LanguageModel, Message, ModelUsage
from .services import reserve_turn


class UserAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser("root", password="Example-admin-947!")
        cls.password = "Example-user-293!"

    def setUp(self):
        self.client.force_login(self.root)

    def add(self, username, role="user", **extra):
        return self.client.post(
            reverse("admin:auth_user_add"),
            {
                "username": username,
                "role": role,
                "is_active": "on",
                "usable_password": "true",
                "password1": self.password,
                "password2": self.password,
                **extra,
            },
        )

    def edit(self, user, role="user", active=True, **extra):
        data = {"username": user.username, "role": role, **extra}
        if active:
            data["is_active"] = "on"
        return self.client.post(reverse("admin:auth_user_change", args=[user.pk]), data)

    def test_new_admin_can_sign_in_and_manage_both_roles(self):
        self.assertEqual(self.add("second", "admin").status_code, 302)
        user = User.objects.get(username="second")
        self.assertTrue(
            user.is_staff and user.is_superuser and user.check_password(self.password)
        )
        self.client.logout()
        response = self.client.post(
            reverse("admin:login"),
            {"username": "second", "password": self.password, "next": "/admin/"},
        )
        self.assertRedirects(response, reverse("admin:index"))
        self.assertEqual(self.client.get("/api/usage/").status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse("admin:portal_modelconnection_changelist")
            ).status_code,
            200,
        )
        self.assertEqual(self.add("third", "admin").status_code, 302)
        self.assertEqual(self.add("ordinary").status_code, 302)
        third = User.objects.get(username="third")
        self.assertEqual(self.edit(third, role="user").status_code, 302)
        third.refresh_from_db()
        self.assertFalse(third.is_staff or third.is_superuser)
        self.assertEqual(self.edit(third, role="admin").status_code, 302)
        third.refresh_from_db()
        self.assertTrue(third.is_staff and third.is_superuser)

    def test_user_creation_ignores_legacy_quota_and_zero_credit_blocks_paid_model(self):
        default = Account._meta.get_field("token_limit").get_default()
        page = self.client.get(reverse("admin:auth_user_add"))
        self.assertContains(page, 'name="role"')
        self.assertNotContains(page, 'name="token_limit"')
        self.assertEqual(self.add("default").status_code, 302)
        self.assertEqual(
            self.add(
                "zero",
                initial_credit="0",
                token_limit="0",
                is_staff="on",
                is_superuser="on",
                tokens_used="99",
            ).status_code,
            302,
        )
        for name in ["default", "zero"]:
            user = User.objects.get(username=name)
            self.assertFalse(user.is_staff or user.is_superuser)
            self.assertEqual(
                (user.account.token_limit, user.account.tokens_used), (default, 0)
            )
            self.assertEqual(self.edit(user, first_name="changed").status_code, 302)
            self.assertEqual(Account.objects.filter(user=user).count(), 1)
        portal = Client()
        portal.force_login(User.objects.get(username="zero"))
        chat = Conversation.objects.create(
            user_id=portal.session["_auth_user_id"], title="quota"
        )
        model = LanguageModel.objects.create(
            input_price_per_million_rial=1000000,
            output_price_per_million_rial=1000000,
            name="demo",
            provider="demo",
            model_id="demo",
        )
        self.assertEqual(
            portal.post(
                f"/api/conversations/{chat.pk}/",
                {"model_ids": [model.pk], "content": "q"},
                content_type="application/json",
            ).status_code,
            400,
        )
        self.assertFalse(chat.messages.exists())

    def test_invalid_credit_role_or_password_never_creates_user(self):
        for bad in ["-1", "1.33", "abc", str(2**63)]:
            response = self.add("invalid", initial_credit=bad)
            self.assertIn("initial_credit", response.context["adminform"].form.errors)
        self.assertIn(
            "role", self.add("invalid", role="staff").context["adminform"].form.errors
        )
        self.assertIn(
            "password2",
            self.add("invalid", password2="mismatch").context["adminform"].form.errors,
        )
        self.assertFalse(User.objects.filter(username="invalid").exists())

    def test_user_edits_preserve_historical_quota_usage_and_password_flow(self):
        user = User.objects.create_user("existing", password=self.password)
        Account.objects.filter(user=user).update(token_limit=200, tokens_used=135)
        page = self.client.get(reverse("admin:auth_user_change", args=[user.pk]))
        self.assertNotContains(page, 'name="token_limit"')
        self.assertContains(page, "135")
        self.assertEqual(
            self.edit(
                user, token_limit="600", tokens_used="0", first_name="Ali"
            ).status_code,
            302,
        )
        user.refresh_from_db()
        self.assertEqual(
            (user.first_name, user.account.token_limit, user.account.tokens_used),
            ("Ali", 200, 135),
        )
        response = self.client.post(
            reverse("admin:auth_user_password_change", args=[user.pk]),
            {
                "usable_password": "true",
                "password1": "Changed-password-348!",
                "password2": "Changed-password-348!",
            },
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password("Changed-password-348!"))
        account_url = reverse("admin:portal_account_change", args=[user.account.pk])
        self.assertNotContains(self.client.get(account_url), 'name="token_limit"')
        self.assertEqual(
            self.client.post(
                account_url,
                {"token_limit": "450", "tokens_used": 0, "user": self.root.pk},
            ).status_code,
            403,
        )
        user.account.refresh_from_db()
        self.assertEqual(
            (user.account.token_limit, user.account.tokens_used), (200, 135)
        )

    def test_user_and_legacy_staff_cannot_manage_roles_quota_or_other_users(self):
        other = Conversation.objects.create(user=self.root, title="private")
        for staff in (False, True):
            user = User.objects.create_user(
                f"limited-{staff}", password=self.password, is_staff=staff
            )
            user.user_permissions.add(
                *Permission.objects.filter(
                    codename__in=["add_user", "change_user", "change_account"]
                )
            )
            limited = Client()
            limited.force_login(user)
            for path, data in [
                (
                    reverse("admin:auth_user_add"),
                    {"username": "elevated", "role": "admin"},
                ),
                (
                    reverse("admin:auth_user_change", args=[user.pk]),
                    {"username": user.username, "role": "admin", "token_limit": 1},
                ),
                (reverse("admin:auth_user_password_change", args=[self.root.pk]), {}),
                (
                    reverse("admin:portal_account_change", args=[user.account.pk]),
                    {"token_limit": "1"},
                ),
            ]:
                self.assertEqual(limited.post(path, data).status_code, 302)
            self.assertEqual(limited.get(reverse("admin:index")).status_code, 302)
            self.assertEqual(limited.get("/api/usage/").status_code, 403)
            self.assertFalse(limited.get("/api/auth/me/").json()["is_staff"])
            self.assertEqual(
                limited.post(
                    "/api/auth/me/", {"role": "admin", "token_limit": 1}
                ).status_code,
                405,
            )
            self.assertEqual(
                limited.get(f"/api/conversations/{other.pk}/").status_code, 404
            )
            user.refresh_from_db()
            self.assertFalse(user.is_superuser)
            self.assertEqual(
                user.account.token_limit,
                Account._meta.get_field("token_limit").get_default(),
            )
            limited.logout()
            response = limited.post(
                reverse("admin:login"),
                {"username": user.username, "password": self.password},
            )
            self.assertTrue(response.context["form"].non_field_errors())
            self.assertNotIn("_auth_user_id", limited.session)
        self.assertFalse(User.objects.filter(username="elevated").exists())

    def test_deactivate_blocks_existing_session_and_stale_admission_then_reactivate(
        self,
    ):
        user = User.objects.create_user("member", password=self.password)
        portal = Client()
        self.assertEqual(
            portal.post(
                "/api/auth/login/",
                {"username": user.username, "password": self.password},
                content_type="application/json",
            ).status_code,
            200,
        )
        model = LanguageModel.objects.create(
            input_price_per_million_rial=1000000,
            output_price_per_million_rial=1000000,
            provider="demo",
            name="demo",
            model_id="d",
        )
        change_credit(user.pk, "grant", 10000, "setup", "test")
        chat = Conversation.objects.create(user=user, title="retained")
        url = f"/api/conversations/{chat.pk}/"
        payload = {"content": "hello", "model_ids": [model.pk]}
        self.assertEqual(
            portal.post(url, payload, content_type="application/json").status_code, 200
        )
        before = portal.get("/api/auth/me/").json()
        self.assertGreater(before["tokens_used"], 0)
        ledger = ModelUsage.objects.get(user=user)
        self.assertEqual(self.edit(user, active=False).status_code, 302)
        listing = self.client.get(
            reverse("admin:auth_user_changelist"), {"is_active__exact": "0"}
        )
        self.assertEqual(list(listing.context["cl"].queryset), [user])
        self.assertIn("is_active", listing.context["cl"].list_display)
        for path in ["/api/auth/me/", "/api/models/", "/api/conversations/", url]:
            self.assertEqual(portal.get(path).status_code, 403)
        with patch("portal.streaming.stream_complete") as provider:
            for path in [url, url + "stream/"]:
                self.assertEqual(
                    portal.post(
                        path, payload, content_type="application/json"
                    ).status_code,
                    403,
                )
            with self.assertRaises(PermissionDenied):
                reserve_turn(user, chat, "stale", [model.pk])
            provider.assert_not_called()
        self.assertEqual(
            Client()
            .post(
                "/api/auth/login/",
                {"username": user.username, "password": self.password},
                content_type="application/json",
            )
            .status_code,
            400,
        )
        old = Conversation.objects.create(user=user, title="expired")
        Conversation.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=31)
        )
        call_command("purge_history")
        self.assertFalse(Conversation.objects.filter(pk=old.pk).exists())
        self.assertEqual(Message.objects.filter(conversation=chat).count(), 2)
        self.assertEqual(self.edit(user).status_code, 302)
        portal.logout()
        self.assertTrue(portal.login(username=user.username, password=self.password))
        self.assertEqual(portal.get("/api/auth/me/").json(), before)
        self.assertEqual(len(portal.get(url).json()["messages"]), 2)
        self.assertEqual(
            ModelUsage.objects.get(pk=ledger.pk).output_tokens, ledger.output_tokens
        )


class AccountBackfillTests(TransactionTestCase):
    def test_backfill_only_missing_profiles(self):
        executor = MigrationExecutor(connection)
        before = [("portal", "0006_thinking_and_token_usage")]
        executor.migrate(before)
        try:
            old = executor.loader.project_state(before).apps
            users = old.get_model("auth", "User")
            accounts = old.get_model("portal", "Account")
            missing = users.objects.create(username="missing-profile")
            existing = users.objects.create(username="has-profile")
            accounts.objects.create(user=existing, token_limit=809, tokens_used=402)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
        self.assertEqual(
            (
                Account.objects.get(user_id=existing.pk).token_limit,
                Account.objects.get(user_id=existing.pk).tokens_used,
            ),
            (809, 402),
        )
        self.assertEqual(
            Account.objects.get(user_id=missing.pk).token_limit,
            Account._meta.get_field("token_limit").get_default(),
        )
