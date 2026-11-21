"""Connection routing uses MockTransport: no real credential or paid request."""

import json
import os
from contextlib import contextmanager
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from .models import Account, Conversation, LanguageModel, ModelConnection, ModelUsage
from .providers import ProviderError, complete


@contextmanager
def upstream(handler):
    async_class = httpx.AsyncClient
    client_class = httpx.Client
    with (
        patch(
            "portal.providers.httpx.Client",
            side_effect=lambda **kwargs: client_class(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        ),
        patch(
            "portal.providers.httpx.AsyncClient",
            side_effect=lambda **kw: async_class(
                transport=httpx.MockTransport(handler), **kw
            ),
        ),
    ):
        yield


def success(content="answer"):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        },
    )


class ConnectionTests(TestCase):
    def setUp(self):
        self.a = ModelConnection.objects.create(
            name="service A",
            base_url="https://first.example/v1/",
            api_key_env="LLM_FIRST_API_KEY",
        )
        self.b = ModelConnection.objects.create(
            name="service B",
            base_url="https://second.example/api/v1",
            api_key_env="LLM_SECOND_API_KEY",
        )
        self.model_a = LanguageModel.objects.create(
            name="A", provider="openai", model_id="shared-id", connection=self.a
        )
        self.model_b = LanguageModel.objects.create(
            name="B", provider="openai", model_id="shared-id", connection=self.b
        )
        self.messages = [{"role": "user", "content": "hello"}]

    def test_admin_can_create_connection_and_attach_model(self):
        admin = get_user_model().objects.create_superuser(
            "connection-admin", password="test-password"
        )
        self.client.force_login(admin)
        self.assertEqual(
            self.client.get("/admin/portal/modelconnection/add/").status_code, 200
        )
        result = self.client.post(
            "/admin/portal/modelconnection/add/",
            {
                "name": "Admin service",
                "base_url": "https://admin.example/v1",
                "api_key_env": "LLM_ADMIN_SERVICE_API_KEY",
                "enabled": "on",
                "_save": "Save",
            },
        )
        self.assertEqual(result.status_code, 302)
        configured = ModelConnection.objects.get(name="Admin service")
        result = self.client.post(
            "/admin/portal/languagemodel/add/",
            {
                "name": "Admin model",
                "provider": "openai",
                "connection": configured.pk,
                "model_id": "new-id",
                "context_window": 8192,
                "max_output_tokens": 512,
                "thinking_contract": "none",
                "output_parameter": "max_tokens",
                "stream_usage_option": "on",
                "framing_tokens": 32,
                "reasoning_policy": "hidden",
                "enabled": "on",
                "_save": "Save",
            },
        )
        self.assertEqual(result.status_code, 302)
        self.assertEqual(
            LanguageModel.objects.get(name="Admin model").connection_id, configured.pk
        )

    def test_each_connection_uses_only_its_endpoint_and_key(self):
        seen = []

        def handler(request):
            seen.append(
                (
                    str(request.url),
                    request.headers.get("Authorization"),
                    json.loads(request.content)["model"],
                )
            )
            return success()

        with (
            patch.dict(
                os.environ,
                {
                    "LLM_FIRST_API_KEY": "first-test-key",
                    "LLM_SECOND_API_KEY": "second-test-key",
                },
            ),
            upstream(handler),
        ):
            self.assertEqual(complete(self.model_a, self.messages), ("answer", 10, 20))
            complete(self.model_b, self.messages)
        self.assertEqual(
            seen,
            [
                (
                    "https://first.example/v1/chat/completions",
                    "Bearer first-test-key",
                    "shared-id",
                ),
                (
                    "https://second.example/api/v1/chat/completions",
                    "Bearer second-test-key",
                    "shared-id",
                ),
            ],
        )

    def test_multiple_models_share_one_connection(self):
        extra = LanguageModel.objects.create(
            name="other", provider="openai", model_id="other-id", connection=self.a
        )
        seen = []

        def handler(request):
            seen.append(
                (request.headers["Authorization"], json.loads(request.content)["model"])
            )
            return success()

        with (
            patch.dict(os.environ, {"LLM_FIRST_API_KEY": "shared-test-key"}),
            upstream(handler),
        ):
            complete(self.model_a, self.messages)
            complete(extra, self.messages)
        self.assertEqual(
            seen,
            [
                ("Bearer shared-test-key", "shared-id"),
                ("Bearer shared-test-key", "other-id"),
            ],
        )

    def test_missing_key_does_not_fall_back_to_legacy_key(self):
        with (
            patch.dict(
                os.environ, {"LLM_API_KEY": "legacy-test-key", "LLM_FIRST_API_KEY": ""}
            ),
            patch("portal.providers.httpx.Client") as client,
        ):
            with self.assertRaises(ProviderError):
                complete(self.model_a, self.messages)
            client.assert_not_called()

    def test_disabled_or_missing_connection_never_calls_http(self):
        with patch("portal.providers.httpx.Client") as client:
            self.a.enabled = False
            with self.assertRaises(ProviderError):
                complete(self.model_a, self.messages)
            self.model_a.connection = None
            with self.assertRaises(ProviderError):
                complete(self.model_a, self.messages)
            client.assert_not_called()

    def test_keyless_local_connection_sends_no_authorization(self):
        self.a.base_url = "http://localhost:11434/v1"
        self.a.api_key_env = ""

        def handler(request):
            self.assertNotIn("Authorization", request.headers)
            self.assertEqual(request.url.host, "localhost")
            return success()

        with upstream(handler):
            complete(self.model_a, self.messages)

    def test_invalid_urls_and_secret_references_rejected_before_network(self):
        for value in [
            "ftp://first.example/v1",
            "https://user:password@first.example/v1",
            "https://first.example/v1?api_key=secret",
            "https://first.example/v1#fragment",
            "https://first.example/v1?",
            "https://first.example/v1#",
        ]:
            self.a.base_url = value
            with (
                self.subTest(url=value),
                patch("portal.providers.httpx.Client") as client,
            ):
                with self.assertRaises(ProviderError):
                    complete(self.model_a, self.messages)
                client.assert_not_called()
        self.a.base_url = "https://first.example/v1"
        for value in [
            "POSTGRES_PASSWORD",
            "DJANGO_SECRET_KEY",
            "actual-secret-key-value",
            "LLM_API_KEY\n",
        ]:
            self.a.api_key_env = value
            with (
                self.subTest(reference=value),
                patch("portal.providers.httpx.Client") as client,
            ):
                with self.assertRaises(ProviderError):
                    complete(self.model_a, self.messages)
                client.assert_not_called()

    def test_admin_model_validation_and_connection_protection(self):
        self.model_a.connection = None
        with self.assertRaises(ValidationError):
            self.model_a.full_clean()
        self.model_a.connection = self.a
        self.model_a.provider = "demo"
        with self.assertRaises(ValidationError):
            self.model_a.full_clean()
        with self.assertRaises(ProtectedError):
            self.a.delete()

    def test_redirect_is_not_followed_with_credentials(self):
        seen = []

        def handler(request):
            seen.append(str(request.url))
            return httpx.Response(
                307,
                headers={"Location": "https://unrelated.example/v1/chat/completions"},
            )

        with (
            patch.dict(os.environ, {"LLM_FIRST_API_KEY": "first-test-key"}),
            upstream(handler),
        ):
            with self.assertRaises(ProviderError):
                complete(self.model_a, self.messages)
        self.assertEqual(seen, ["https://first.example/v1/chat/completions"])

    def test_api_comparison_routing_partial_failure_and_no_connection_leak(self):
        user = get_user_model().objects.create_user("connections")
        account = Account.objects.get(user=user)
        chat = Conversation.objects.create(user=user, title="comparison")
        client = APIClient()
        client.force_authenticate(user)
        models = client.get("/api/models/").data
        self.assertEqual(
            set(models[0]),
            {
                "id",
                "name",
                "provider",
                "context_window",
                "max_output_tokens",
                "thinking_levels",
                "thinking_default",
                "reasoning_supported",
            },
        )

        def handler(request):
            if request.url.host == "second.example":
                return httpx.Response(
                    401, text="private upstream response second-test-key"
                )
            return success()

        with (
            patch.dict(
                os.environ,
                {
                    "LLM_FIRST_API_KEY": "first-test-key",
                    "LLM_SECOND_API_KEY": "second-test-key",
                },
            ),
            upstream(handler),
        ):
            result = client.post(
                f"/api/conversations/{chat.pk}/",
                {"content": "hello", "model_ids": [self.model_a.pk, self.model_b.pk]},
                format="json",
            )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.data["errors"]), 1)
        self.assertEqual(result.data["errors"][0]["model"], "B")
        payload = json.dumps(result.data)
        for private in [
            "first.example",
            "second.example",
            "test-key",
            "LLM_FIRST_API_KEY",
            "private upstream",
        ]:
            self.assertNotIn(private, payload)
        account.refresh_from_db()
        self.assertEqual(account.tokens_used, 30)
        self.assertEqual(
            ModelUsage.objects.get(user=user, model=self.model_a).input_tokens, 10
        )
        self.assertFalse(
            ModelUsage.objects.filter(user=user, model=self.model_b).exists()
        )


class ConnectionMigrationTests(TransactionTestCase):
    def test_legacy_models_keep_old_endpoint_and_env_reference(self):
        before = [("portal", "0002_modelusage")]
        after = [("portal", "0003_modelconnection_languagemodel_connection")]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            old = executor.loader.project_state(before).apps.get_model(
                "portal", "LanguageModel"
            )
            real = old.objects.create(
                name="legacy", provider="openai", model_id="existing"
            )
            demo = old.objects.create(name="demo", provider="demo", model_id="demo")
            with self.settings(LLM_BASE_URL="https://legacy.example/v1"):
                executor = MigrationExecutor(connection)
                executor.migrate(after)
            apps = executor.loader.project_state(after).apps
            Model = apps.get_model("portal", "LanguageModel")
            Connection = apps.get_model("portal", "ModelConnection")
            migrated = Connection.objects.get(
                pk=Model.objects.get(pk=real.pk).connection_id
            )
            self.assertEqual(migrated.base_url, "https://legacy.example/v1")
            self.assertEqual(migrated.api_key_env, "LLM_API_KEY")
            self.assertIsNone(Model.objects.get(pk=demo.pk).connection_id)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())

    def test_legacy_unanswered_questions_stay_out_of_model_context(self):
        before = [("portal", "0003_modelconnection_languagemodel_connection")]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            user = apps.get_model("auth", "User").objects.create(username="history")
            chat = apps.get_model("portal", "Conversation").objects.create(
                user=user, title="old"
            )
            model = apps.get_model("portal", "LanguageModel").objects.create(
                name="old", provider="demo"
            )
            rows = apps.get_model("portal", "Message").objects
            orphan = rows.create(conversation=chat, role="user", content="unanswered")
            prompt = rows.create(conversation=chat, role="user", content="answered")
            answer = rows.create(
                conversation=chat,
                role="assistant",
                content="ok",
                model=model,
                input_tokens=5,
                output_tokens=1,
            )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())

        from .models import Message
        from .services import reserve_turn

        self.assertEqual(Message.objects.get(pk=orphan.pk).status, "failed")
        self.assertEqual(Message.objects.get(pk=prompt.pk).status, "completed")
        reply = Message.objects.get(pk=answer.pk)
        self.assertEqual(
            (reply.parent_id, reply.input_tokens, reply.output_tokens),
            (prompt.pk, 5, 1),
        )
        self.assertEqual(
            (reply.total_tokens, reply.reasoning_tokens, reply.reasoning_content),
            (6, None, None),
        )
        current_user = get_user_model().objects.get(pk=user.pk)
        current_chat = Conversation.objects.get(pk=chat.pk)
        _, jobs = reserve_turn(current_user, current_chat, "next", [model.pk])
        self.assertEqual(
            [m["content"] for m in jobs[0].messages], ["answered", "ok", "next"]
        )
