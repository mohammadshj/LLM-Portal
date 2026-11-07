from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from time import sleep
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from .models import Account, Conversation, LanguageModel, Message, ModelUsage
from .providers import ProviderError, complete
from .services import send_message


class PortalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "alice", password="test-strong-password"
        )
        self.other = get_user_model().objects.create_user(
            "bob", password="test-strong-password"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.account = Account.objects.create(user=self.user)
        self.a = LanguageModel.objects.create(
            name="A", model_id="a", provider="demo", max_output_tokens=2048
        )
        self.b = LanguageModel.objects.create(
            name="B", model_id="b", provider="demo", max_output_tokens=2048
        )
        self.conversation = Conversation.objects.create(user=self.user, title="test")
        self.url = f"/api/conversations/{self.conversation.pk}/"

    def send(self, **overrides):
        return self.client.post(
            self.url,
            {"content": "سلام", "model_ids": [self.a.pk], **overrides},
            format="json",
        )

    def test_authentication_required(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/models/").status_code, 403)

    def test_user_cannot_read_write_or_delete_another_conversation(self):
        self.client.force_authenticate(self.other)
        for method in ["get", "post", "delete"]:
            self.assertEqual(getattr(self.client, method)(self.url).status_code, 404)
        self.assertEqual(self.client.get("/api/conversations/").data["results"], [])

    def test_comparison_records_usage_and_separate_histories(self):
        with patch(
            "portal.services.complete", return_value=("answer", 10, 20)
        ) as provider:
            self.assertEqual(
                self.send(model_ids=[self.a.pk, self.b.pk]).status_code, 200
            )
            self.assertEqual(Message.objects.count(), 3)
            self.account.refresh_from_db()
            self.assertEqual(self.account.tokens_used, 60)
            self.assertEqual(ModelUsage.objects.count(), 2)
            self.send()
            history = provider.call_args.args[1]
            self.assertEqual(
                [m["role"] for m in history], ["user", "assistant", "user"]
            )

    def test_insufficient_quota_never_calls_provider(self):
        self.account.token_limit = 1
        self.account.save()
        with patch("portal.services.complete") as provider:
            self.assertEqual(self.send().status_code, 400)
            provider.assert_not_called()
        self.assertFalse(Message.objects.exists())

    def test_context_rejection_never_calls_provider(self):
        self.a.context_window = 10
        self.a.save()
        with patch("portal.services.complete") as provider:
            self.assertEqual(self.send().status_code, 400)
            provider.assert_not_called()

    def test_duplicate_disabled_and_invalid_inputs(self):
        self.assertEqual(self.send(model_ids=[self.a.pk, self.a.pk]).status_code, 400)
        self.assertEqual(self.send(content="  ").status_code, 400)
        self.a.enabled = False
        self.a.save()
        self.assertEqual(self.send().status_code, 400)

    def test_partial_failure_preserves_success_and_usage(self):
        with patch(
            "portal.services.complete",
            side_effect=[("answer", 10, 20), ProviderError("unavailable")],
        ):
            result = self.send(model_ids=[self.a.pk, self.b.pk])
        self.assertEqual(len(result.data["errors"]), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.tokens_used, 30)
        self.assertEqual(Message.objects.filter(role="assistant").count(), 1)

    def test_retention_preserves_usage(self):
        self.send()
        Conversation.objects.filter(pk=self.conversation.pk).update(
            created_at=timezone.now() - timedelta(days=31)
        )
        self.assertEqual(self.client.get(self.url).status_code, 404)
        call_command("purge_history")
        self.assertFalse(Conversation.objects.exists())
        self.assertTrue(ModelUsage.objects.exists())
        self.account.refresh_from_db()
        self.assertGreater(self.account.tokens_used, 0)

    def test_report_requires_admin(self):
        self.assertEqual(self.client.get("/api/usage/").status_code, 403)
        self.user.is_staff = True
        self.user.save()
        self.assertEqual(self.client.get("/api/usage/").status_code, 200)

    def test_login_and_logout_enforce_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        data = {"username": "alice", "password": "test-strong-password"}
        self.assertEqual(
            client.post("/api/auth/login/", data, format="json").status_code, 403
        )
        csrf = client.get("/api/auth/csrf/").json()["csrfToken"]
        self.assertEqual(
            client.post(
                "/api/auth/login/", data, format="json", HTTP_X_CSRFTOKEN=csrf
            ).status_code,
            200,
        )
        self.assertEqual(client.get("/api/auth/me/").status_code, 200)
        self.assertEqual(client.post("/api/auth/logout/").status_code, 403)
        csrf = client.get("/api/auth/csrf/").json()["csrfToken"]
        self.assertEqual(
            client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=csrf).status_code, 204
        )
        self.assertEqual(client.get("/api/auth/me/").status_code, 403)

    def test_missing_real_provider_key(self):
        self.a.provider = "openai"
        with self.settings(LLM_API_KEY=""):
            with self.assertRaises(ProviderError):
                complete(self.a, [{"role": "user", "content": "test"}])


class ConcurrentQuotaTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_parallel_requests_cannot_spend_same_quota(self):
        user = get_user_model().objects.create_user("parallel")
        account = Account.objects.create(user=user, token_limit=2120)
        model = LanguageModel.objects.create(
            name="mock", model_id="mock", provider="demo", max_output_tokens=2048
        )
        conversation = Conversation.objects.create(user=user, title="parallel")
        start = Barrier(2)

        def provider(*args):
            sleep(0.15)  # Expose an interleaving if the database lock is removed.
            return "answer", 10, 2048

        def worker(_):
            close_old_connections()
            try:
                start.wait(timeout=5)
                send_message(user, conversation, "hello", [model.pk])
                return "sent"
            except ValidationError:
                return "quota"
            finally:
                connection.close()

        with patch("portal.services.complete", side_effect=provider) as upstream:
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(worker, range(2)))
        self.assertCountEqual(outcomes, ["sent", "quota"])
        self.assertEqual(upstream.call_count, 1)
        account.refresh_from_db()
        self.assertEqual(account.tokens_used, 2058)
