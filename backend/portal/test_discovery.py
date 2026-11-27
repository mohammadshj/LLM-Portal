import json
import os
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from tempfile import NamedTemporaryFile
from contextlib import contextmanager
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import (
    Client,
    SimpleTestCase,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.utils import timezone

from .capabilities import resolve, runtime_model
from .discovery import sync_models
from .discovery_http import DiscoveryError, allowed_ip, read_json
from .models import (
    Account,
    Conversation,
    LanguageModel,
    Message,
    ModelConnection,
    RegistrySnapshot,
)
from .providers import ProviderError, _target
from .registry import update_registry
from .serializers import ModelSerializer
from .test_connections import upstream


@contextmanager
def catalog_server():
    state = {"body": {"data": [{"id": "model-a"}]}, "status": 200, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state["requests"].append(
                (self.path, self.headers.get("Authorization"), self.headers["Host"])
            )
            body = json.dumps(state["body"]).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Location", "/other")
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            with override_settings(DISCOVERY_LOCAL_ORIGINS={origin}):
                yield origin, state
        finally:
            server.shutdown()
            thread.join()


class TransportTests(SimpleTestCase):
    def test_private_and_special_addresses_require_correct_policy(self):
        for ip in [
            "169.254.169.254",
            "fd00:ec2::254",
            "0.0.0.0",
            "224.0.0.5",
            "::ffff:127.0.0.1",
            "100.100.100.200",
            "168.63.129.16",
            "fe80::1",
        ]:
            self.assertFalse(allowed_ip(ip, True), ip)
        for ip in ["127.0.0.1", "10.2.3.4", "fd01::12"]:
            self.assertFalse(allowed_ip(ip, False))
            self.assertTrue(allowed_ip(ip, True))
        self.assertTrue(allowed_ip("8.8.8.8", False))
        with self.assertRaisesMessage(DiscoveryError, "نشانی"):
            read_json("https://127.0.0.1/models", "", 1024)

    def test_pinned_ip_host_and_tls_name_no_environment_proxy(self):
        seen = {}

        def respond(request):
            seen.update(
                host=request.url.host,
                header=request.headers["host"],
                sni=request.extensions["sni_hostname"],
            )
            return httpx.Response(200, stream=httpx.ByteStream(b'{"data":[]}'))

        cls = httpx.AsyncClient

        def client(**kw):
            self.assertFalse(kw["trust_env"])
            self.assertFalse(kw["follow_redirects"])
            return cls(transport=httpx.MockTransport(respond), **kw)

        record = (2, 1, 6, "", ("8.8.8.8", 443))
        with (
            patch("socket.getaddrinfo", return_value=[record]) as dns,
            patch("portal.discovery_http.httpx.AsyncClient", side_effect=client),
        ):
            self.assertEqual(
                read_json("https://service.example/v1/models", "", 100), {"data": []}
            )
            self.assertEqual(dns.call_count, 1)
        self.assertEqual(
            seen,
            {"host": "8.8.8.8", "header": "service.example", "sni": "service.example"},
        )
        with (
            patch(
                "socket.getaddrinfo",
                return_value=[record, (2, 1, 6, "", ("10.0.0.1", 443))],
            ),
            self.assertRaises(DiscoveryError),
        ):
            read_json("https://service.example/models", "", 100)

    def test_response_size_redirect_auth_and_network_errors(self):
        with catalog_server() as (origin, state):
            with self.assertRaises(DiscoveryError):
                read_json(origin + "/models", "", 5)
            for status, code in [
                (401, "auth"),
                (403, "auth"),
                (404, "endpoint"),
                (429, "rate_limit"),
                (503, "http"),
                (307, "redirect"),
            ]:
                state["status"] = status
                with self.assertRaises(DiscoveryError) as cm:
                    read_json(origin + "/models", "abc", 100)
                self.assertEqual(
                    (cm.exception.code, cm.exception.status), (code, status)
                )
            self.assertTrue(all(row[0] == "/models" for row in state["requests"]))
        with (
            patch("socket.getaddrinfo", side_effect=OSError()),
            self.assertRaises(DiscoveryError) as cm,
        ):
            read_json("https://service.example/models", "", 100)
        self.assertEqual(cm.exception.code, "network")
        with (
            patch("socket.getaddrinfo", side_effect=TimeoutError()),
            self.assertRaises(DiscoveryError) as cm,
        ):
            read_json("https://service.example/models", "", 100)
        self.assertEqual(cm.exception.code, "timeout")


class DiscoveryTests(TestCase):
    def setUp(self):
        self.conn = ModelConnection.objects.create(
            name="C", base_url="https://gateway.example/v1", api_key_env=""
        )
        self.user = get_user_model().objects.create_user("member")
        self.chat = Conversation.objects.create(user=self.user, title="chat")
        self.client.force_login(self.user)

    def sync(self, rows):
        with patch("portal.discovery.read_json", return_value={"data": rows}):
            return sync_models(self.conn.pk)

    def test_sync_admin_button_csrf_and_local_server(self):
        admin = get_user_model().objects.create_superuser("admin")
        endpoint = f"/admin/portal/modelconnection/{self.conn.pk}/sync-models/"
        self.assertNotEqual(self.client.post(endpoint).status_code, 200)
        self.assertFalse(LanguageModel.objects.exists())
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(admin)
        change = f"/admin/portal/modelconnection/{self.conn.pk}/change/"
        self.assertContains(browser.get(change), "Sync Models")
        self.assertEqual(browser.get(endpoint).status_code, 405)
        self.assertEqual(browser.post(endpoint).status_code, 403)
        with (
            catalog_server() as (origin, state),
            patch.dict(os.environ, {"LLM_TEST_API_KEY": "sample-secret"}),
        ):
            self.conn.base_url = origin + "/v1"
            self.conn.api_key_env = "LLM_TEST_API_KEY"
            self.conn.save()
            response = browser.post(
                endpoint, HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value
            )
            self.assertRedirects(response, change)
            self.assertEqual(
                state["requests"],
                [("/v1/models", "Bearer sample-secret", origin.split("//")[1])],
            )
            self.assertFalse(self.conn.models.get().enabled)
            state["status"] = 401
            with self.assertRaises(DiscoveryError):
                sync_models(self.conn.pk)
            self.conn.refresh_from_db()
            self.assertEqual(
                self.conn.sync_result,
                {"status": "failed", "code": "auth", "http_status": 401},
            )
            self.assertNotIn(
                "sample-secret", repr(self.conn.models.get().discovery_data)
            )

    def test_idempotency_missing_duplicates_manual_names_invalid_entries(self):
        row = {
            "id": "x",
            "name": "Display",
            "capabilities": {"streaming": False, "vision": True},
            "secret": "private",
        }
        result = self.sync([row, row, None, {"id": "bad\n"}])
        self.assertEqual(
            (result["added"], result["duplicates"], result["errors"]), (1, 1, 2)
        )
        model = self.conn.models.get()
        self.assertIsNone(model.input_price_per_million_rial)
        model.input_price_per_million_rial, model.output_price_per_million_rial = 12, 34
        model.save(
            update_fields=[
                "input_price_per_million_rial",
                "output_price_per_million_rial",
            ]
        )
        self.assertNotIn("private", repr(model.discovery_data))
        self.assertEqual(self.sync([row])["unchanged"], 1)
        self.assertEqual(self.sync([{**row, "name": "New display"}])["updated"], 1)
        model.refresh_from_db()
        self.assertEqual(model.name, "New display")
        self.assertEqual(
            (model.input_price_per_million_rial, model.output_price_per_million_rial),
            (12, 34),
        )
        model.name, model.enabled, model.capability_overrides = (
            "Manual",
            True,
            {"vision": False},
        )
        model.save()
        self.sync(
            [
                {
                    **row,
                    "name": "Newer",
                    "capabilities": {"vision": True, "streaming": True},
                }
            ]
        )
        model.refresh_from_db()
        self.assertEqual((model.name, model.enabled), ("Manual", True))
        facts, source = resolve(model)
        self.assertEqual(
            (facts["vision"], source["vision"], facts["streaming"]),
            (False, "manual", True),
        )
        self.assertEqual(self.sync([])["absent"], 1)
        self.assertTrue(self.conn.models.filter(pk=model.pk, enabled=True).exists())
        with (
            patch("portal.discovery.read_json", return_value={"data": {}}),
            self.assertRaises(DiscoveryError),
        ):
            sync_models(self.conn.pk)
        self.assertTrue(self.conn.models.filter(pk=model.pk).exists())

    def test_exact_registry_scope_fallback_and_invalid_refresh(self):
        self.conn.discovery_type = "openai"
        self.conn.save()
        row = {
            "reasoning": True,
            "reasoning_options": [
                {"type": "effort", "values": [None, "minimal", "medium", "xhigh"]}
            ],
            "tool_call": True,
            "limit": {"context": 4096, "output": 300},
            "modalities": {"input": ["image", "text"], "output": ["text"]},
        }
        update_registry("openai", {"openai": {"models": {"m": row, "other/m": row}}})
        self.sync([{"id": "m", "capabilities": {"vision": False}}, {"id": "m-latest"}])
        model = self.conn.models.get(model_id="m")
        facts, source = resolve(model)
        self.assertEqual(
            (facts["vision"], source["vision"], source["efforts"]),
            (False, "provider", "registry"),
        )
        conf = runtime_model(model)
        self.assertEqual((conf.context_window, conf.max_output_tokens), (4096, 300))
        self.assertEqual(conf.thinking_levels, ["minimal", "medium", "xhigh"])
        self.assertEqual(conf.thinking_default, "")
        self.assertEqual(
            ModelSerializer(self.conn.models.get(model_id="m-latest")).data[
                "reasoning_supported"
            ],
            None,
        )
        self.assertNotIn("reasoning_effort", _target(conf, [])[2])
        RegistrySnapshot.objects.update(fetched_at=timezone.now() - timedelta(days=10))
        with patch("portal.registry.read_json", side_effect=DiscoveryError("network")):
            self.assertEqual(
                self.sync([{"id": "m", "capabilities": {"reasoning": False}}])[
                    "registry"
                ],
                "stale",
            )
        model.refresh_from_db()
        self.assertEqual(ModelSerializer(model).data["thinking_levels"], [])
        with self.assertRaises(DiscoveryError):
            update_registry("openai", {"openai": {"models": []}})
        self.assertIn("m", RegistrySnapshot.objects.get().models)

    def test_native_efforts_selection_default_and_admission(self):
        row = {
            "id": "r",
            "supported_parameters": [
                {
                    "name": "reasoning_effort",
                    "options": ["none", "medium", "xhigh", "custom-depth"],
                }
            ],
            "default_reasoning_effort": "medium",
        }
        self.sync([row, {"id": "reasoner-unknown"}])
        model = self.conn.models.get(model_id="r")
        model.input_price_per_million_rial = model.output_price_per_million_rial = 0
        model.enabled = True
        model.save()
        wire = []

        def handle(req):
            wire.append(json.loads(req.content))
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "done"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                },
            )

        url = f"/api/conversations/{self.chat.pk}/"
        with upstream(handle):
            for level in ("custom-depth", "none", None, "invented"):
                data = {"model_ids": [model.pk], "content": "q"}
                if level is not None:
                    data["thinking"] = {str(model.pk): level}
                self.assertEqual(
                    self.client.post(
                        url, data, content_type="application/json"
                    ).status_code,
                    400 if level == "invented" else 200,
                )
        self.assertEqual(
            [p["reasoning_effort"] for p in wire], ["custom-depth", "none", "medium"]
        )
        self.assertEqual(Account.objects.get(user=self.user).tokens_used, 21)
        self.assertEqual(Message.objects.filter(role="assistant").count(), 3)
        data = ModelSerializer(model).data
        self.assertEqual(
            data["thinking_levels"], row["supported_parameters"][0]["options"]
        )
        unknown = self.conn.models.get(model_id="reasoner-unknown")
        self.assertEqual(ModelSerializer(unknown).data["thinking_levels"], [])
        with self.assertRaises(ProviderError):
            _target(runtime_model(model), [], "high")

    def test_manual_budget_and_existing_aliases_survive_sync(self):
        model = LanguageModel.objects.create(
            input_price_per_million_rial=0,
            output_price_per_million_rial=0,
            name="legacy",
            provider="openai",
            connection=self.conn,
            model_id="m",
            thinking_contract="budget_tokens",
            thinking_levels=["brief", "extended"],
            thinking_budgets={"brief": 64, "extended": 256},
            thinking_default="brief",
        )
        self.sync([{"id": "m", "capabilities": {"reasoning": False}}])
        model.refresh_from_db()
        conf = runtime_model(model)
        self.assertEqual(
            _target(conf, [], "extended")[2]["thinking"],
            {"type": "enabled", "budget_tokens": 256},
        )
        self.assertEqual(resolve(model)[1]["reasoning"], "manual")
        model.thinking_budgets = {"brief": 999999}
        with self.assertRaises(ValidationError):
            model.full_clean()
        model.pk = None
        with self.assertRaises(IntegrityError), transaction.atomic():
            model.save()
        # Simulate an alias explicitly grandfathered by migration 0009.
        model.legacy_alias = True
        model.save()
        result = self.sync([{"id": "m"}])
        self.assertEqual((result["errors"], result["added"]), (1, 0))

    @override_settings(DISCOVERY_REGISTRY_OFFLINE=True)
    def test_router_nested_parameter_and_endpoint_restrictions(self):
        self.conn.discovery_type = "openrouter"
        self.conn.save()
        update_registry(
            "openrouter",
            {
                "openrouter": {
                    "models": {
                        "a/m": {
                            "reasoning": True,
                            "reasoning_options": [
                                {"type": "effort", "values": ["low", "high"]}
                            ],
                            "tool_call": True,
                        }
                    }
                }
            },
        )
        row = {
            "id": "a/m",
            "supported_parameters": ["reasoning"],
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
            "top_provider": {"max_completion_tokens": 9000},
        }
        with patch("portal.registry.read_json") as external:
            self.assertEqual(self.sync([row])["registry"], "offline")
            external.assert_not_called()
        model = self.conn.models.get()
        self.assertEqual(
            _target(runtime_model(model), [], "high")[2]["reasoning"],
            {"effort": "high"},
        )
        facts, _ = resolve(model)
        self.assertTrue(facts["vision"])
        self.assertFalse(facts["tool_calling"])
        self.sync([{**row, "supported_parameters": ["temperature"]}])
        model.refresh_from_db()
        self.assertEqual(ModelSerializer(model).data["thinking_levels"], [])
        self.conn.base_url = "https://another.example/v1"
        self.conn.save()
        model.refresh_from_db()
        self.assertIsNone(ModelSerializer(model).data["reasoning_supported"])

    @override_settings(DISCOVERY_REGISTRY_OFFLINE=True)
    def test_openrouter_native_catalog_and_mandatory_efforts(self):
        self.conn.discovery_type = "openrouter"
        self.conn.save()
        row = {
            "id": "m",
            "reasoning": {
                "supported_efforts": ["medium", "none", "xhigh", None],
                "default_effort": "medium",
                "default_enabled": False,
                "mandatory": True,
                "supports_max_tokens": True,
            },
            "supported_parameters": ["reasoning", "reasoning_effort"],
            "endpoints": ["/api/v1/chat/completions"],
        }
        with patch("portal.discovery.read_json", return_value={"data": [row]}) as get:
            sync_models(self.conn.pk)
            self.assertEqual(
                get.call_args.args[0], "https://gateway.example/v1/models/user"
            )
            self.assertEqual(
                get.call_args.kwargs["params"], {"output_modalities": "all"}
            )
        model = self.conn.models.get()
        effective = runtime_model(model)
        self.assertTrue(effective.can_chat)
        self.assertEqual(effective.thinking_levels, ["medium", "xhigh"])
        self.assertNotIn("reasoning", _target(effective, [])[2])
        self.assertEqual(
            _target(effective, [], "xhigh")[2]["reasoning"], {"effort": "xhigh"}
        )
        self.assertEqual(resolve(model)[0]["default_effort"], "medium")
        self.sync(
            [
                {
                    **row,
                    "reasoning": {"mandatory": False, "supported_efforts": None},
                    "endpoints": ["/responses"],
                }
            ]
        )
        model.refresh_from_db()
        self.assertIn("none", runtime_model(model).thinking_levels)
        self.assertFalse(runtime_model(model).can_chat)

    def test_lmstudio_native_metadata_and_text_routing(self):
        self.conn.discovery_type = "lmstudio"
        self.conn.save()
        with patch(
            "portal.discovery.read_json",
            return_value={
                "models": [
                    {
                        "key": "local-emb",
                        "type": "embedding",
                        "display_name": "Vectors",
                        "max_context_length": 2048,
                        "capabilities": {"vision": False},
                    }
                ]
            },
        ) as get:
            sync_models(self.conn.pk)
            self.assertEqual(
                get.call_args.args[0], "https://gateway.example/api/v1/models"
            )
        model = self.conn.models.get()
        self.assertEqual(model.name, "Vectors")
        self.assertFalse(runtime_model(model).can_chat)
        model.input_price_per_million_rial = model.output_price_per_million_rial = 0
        model.enabled = True
        model.save()
        with upstream(lambda _: self.fail("attempted text generation")):
            response = self.client.post(
                f"/api/conversations/{self.chat.pk}/",
                {"content": "q", "model_ids": [model.pk]},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)

    def test_incomplete_paginated_catalog_keeps_last_good_models(self):
        self.sync([{"id": "keep"}])
        with patch(
            "portal.discovery.read_json",
            return_value={"data": [{"id": "partial"}], "has_more": True},
        ) as get:
            with self.assertRaises(DiscoveryError) as cm:
                sync_models(self.conn.pk)
            self.assertEqual(cm.exception.code, "pagination")
            self.assertEqual(get.call_count, 1)
        self.assertEqual(
            list(self.conn.models.values_list("model_id", flat=True)), ["keep"]
        )

    def test_reflected_credentials_are_never_imported(self):
        self.conn.api_key_env = "LLM_TEST_API_KEY"
        self.conn.save()
        with patch.dict(os.environ, {"LLM_TEST_API_KEY": "secret-test"}):
            result = self.sync(
                [
                    {"id": "secret-test"},
                    {"id": "valid", "name": "secret-test", "hidden": "secret-test"},
                    {"id": "bad", "supported_reasoning_efforts": ["secret-test"]},
                ]
            )
        self.assertEqual(result["errors"], 2)
        self.assertEqual(self.conn.models.get().name, "valid")
        self.assertNotIn("secret-test", repr(self.conn.models.get().discovery_data))
        self.assertNotIn("secret-test", repr(result))

    @override_settings(DISCOVERY_REGISTRY_OFFLINE=True)
    def test_offline_registry_import_and_management_sync(self):
        with NamedTemporaryFile(mode="w+", suffix=".json") as stream:
            json.dump(
                {
                    "tenant": {
                        "models": {
                            "one": {
                                "reasoning": True,
                                "reasoning_options": [
                                    {"type": "budget_tokens", "min": 1024, "max": 8192}
                                ],
                            }
                        }
                    }
                },
                stream,
            )
            stream.flush()
            call_command(
                "refresh_model_registry", "tenant", file=stream.name, stdout=StringIO()
            )
        self.conn.registry_provider = "tenant"
        self.conn.save()
        with (
            patch("portal.discovery.read_json", return_value={"data": [{"id": "one"}]}),
            patch("portal.registry.read_json") as fetch,
        ):
            call_command("sync_models", self.conn.pk, stdout=StringIO())
        fetch.assert_not_called()
        model = self.conn.models.get()
        self.assertTrue(resolve(model)[0]["reasoning"])
        self.assertEqual(resolve(model)[0]["budget_tokens"], {"min": 1024, "max": 8192})
        self.assertEqual(runtime_model(model).thinking_levels, [])

    def test_ollama_listing_and_busy_guard(self):
        self.conn.discovery_type = "ollama"
        self.conn.save()
        with patch(
            "portal.discovery.read_json", return_value={"models": [{"name": "local:1"}]}
        ) as get:
            sync_models(self.conn.pk)
            self.assertEqual(get.call_args.args[0], "https://gateway.example/api/tags")
        self.conn.sync_started_at = timezone.now()
        self.conn.sync_result = {"status": "running"}
        self.conn.save()
        with self.assertRaises(DiscoveryError) as ctx:
            sync_models(self.conn.pk)
        self.assertEqual(ctx.exception.code, "busy")


class ConcurrentDiscoveryTests(TransactionTestCase):
    def test_second_sync_and_connection_change_during_http(self):
        conn = ModelConnection.objects.create(
            name="busy", base_url="https://old.example/v1", api_key_env=""
        )
        started, release = Event(), Event()

        def waiting(*args, **kwargs):
            started.set()
            if not release.wait(10):
                raise AssertionError("catalog request did not resume")
            return {"data": [{"id": "old-model"}]}

        def worker():
            try:
                sync_models(conn.pk)
            finally:
                connections.close_all()

        with (
            patch("portal.discovery.read_json", side_effect=waiting),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            future = pool.submit(worker)
            try:
                self.assertTrue(started.wait(10))
                with self.assertRaises(DiscoveryError) as cm:
                    sync_models(conn.pk)
                self.assertEqual(cm.exception.code, "busy")
                ModelConnection.objects.filter(pk=conn.pk).update(
                    base_url="https://new.example/v1"
                )
            finally:
                release.set()
            with self.assertRaises(DiscoveryError) as cm:
                future.result(timeout=10)
            self.assertEqual(cm.exception.code, "changed")
        self.assertFalse(conn.models.exists())
        with patch(
            "portal.discovery.read_json", return_value={"data": [{"id": "new-model"}]}
        ):
            self.assertEqual(sync_models(conn.pk)["added"], 1)


class DiscoveryMigrationTests(TransactionTestCase):
    def test_preserves_manual_levels_and_history(self):
        executor = MigrationExecutor(connection)
        before = [("portal", "0007_backfill_accounts")]
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            conn = apps.get_model("portal", "ModelConnection").objects.create(
                name="old",
                base_url="https://test.example/v1",
                api_key_env="LLM_OLD_API_KEY",
            )
            old = apps.get_model("portal", "LanguageModel").objects.create(
                connection=conn,
                provider="openai",
                model_id="legacy",
                name="custom",
                thinking_contract="toggle_effort",
                thinking_levels=["off", "max"],
                thinking_default="max",
            )
            alias = apps.get_model("portal", "LanguageModel").objects.create(
                connection=conn,
                provider="openai",
                model_id="legacy",
                name="custom alias",
            )
            user = apps.get_model("auth", "User").objects.create(username="old")
            chat = apps.get_model("portal", "Conversation").objects.create(
                user=user, title="history"
            )
            reply = apps.get_model("portal", "Message").objects.create(
                conversation=chat,
                role="assistant",
                model=old,
                thinking_level="max",
                content="old answer",
            )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
        model = LanguageModel.objects.get(pk=old.pk)
        self.assertTrue(LanguageModel.objects.get(pk=alias.pk).legacy_alias)
        self.assertFalse(model.legacy_alias)
        self.assertFalse(model.auto_thinking)
        self.assertEqual(runtime_model(model).thinking_levels, ["off", "max"])
        self.assertEqual(model.connection.api_key_env, "LLM_OLD_API_KEY")
        with patch.dict(os.environ, {"LLM_OLD_API_KEY": "old-test-value"}):
            self.assertEqual(
                _target(runtime_model(model), [], "off")[2]["thinking"],
                {"type": "disabled"},
            )
        self.assertEqual(model.reasoning_overrides, {})
        profile = runtime_model(model).reasoning_profile
        self.assertEqual(profile.public()["mode"], "combined")
        self.assertEqual(
            profile.payload({"toggle": False}), {"thinking": {"type": "disabled"}}
        )
        historical = Message.objects.get(pk=reply.pk)
        self.assertEqual(
            (
                historical.thinking_level,
                historical.reasoning_settings,
                historical.content,
            ),
            ("max", {}, "old answer"),
        )
