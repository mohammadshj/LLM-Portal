import json
import os
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as ConfigurationError
from django.test import SimpleTestCase, TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from .models import (
    Account,
    Conversation,
    LanguageModel,
    Message,
    ModelConnection,
    ModelUsage,
)
from .providers import ProviderError, stream_complete
from .services import finish_reply, reserve_turn
from .test_connections import upstream
from .test_providers import connection_model, mock_http, sse
from .thinking import parameters
from .tokens import Usage, input_counter, parse_usage


class ThinkingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("think")
        self.chat = Conversation.objects.create(user=self.user, title="chat")
        self.connection = ModelConnection.objects.create(
            name="test", base_url="https://test.example/v1", api_key_env=""
        )
        self.model = LanguageModel.objects.create(
            name="K",
            provider="openai",
            connection=self.connection,
            model_id="test-model",
            thinking_contract="effort",
            thinking_levels=["low", "high", "max"],
            thinking_default="max",
            reasoning_policy="preserve",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f"/api/conversations/{self.chat.pk}/"
        self.payload = {
            "content": "question",
            "model_ids": [self.model.pk],
            "thinking": {str(self.model.pk): "high"},
        }

    def test_reject_invalid_level_before_reservation_or_http(self):
        for value in ["off", "on", "medium", {}, ["high"]]:
            result = self.client.post(
                self.url,
                {**self.payload, "thinking": {str(self.model.pk): value}},
                format="json",
            )
            self.assertEqual(result.status_code, 400)
        self.assertEqual(
            self.client.post(
                self.url, {**self.payload, "thinking": {"other": "low"}}, format="json"
            ).status_code,
            400,
        )
        self.assertFalse(Message.objects.exists())

    def test_json_contract_replay_and_exact_usage(self):
        requests = []

        def handle(req):
            requests.append(json.loads(req.content))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "answer", "reasoning_content": "سابق"}}
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 8,
                        "total_tokens": 18,
                        "completion_tokens_details": {"reasoning_tokens": 6},
                    },
                },
            )

        with upstream(handle):
            for level in ["high", "low"]:
                self.payload["thinking"][str(self.model.pk)] = level
                response = self.client.post(self.url, self.payload, format="json")
                self.assertEqual(response.status_code, 200)
                reply = response.data["messages"][-1]
                self.assertEqual(
                    (
                        reply["thinking_level"],
                        reply["reasoning_content"],
                        reply["content"],
                    ),
                    (level, "سابق", "answer"),
                )
                self.assertEqual(
                    (
                        reply["reasoning_tokens"],
                        reply["total_tokens"],
                        reply["usage_source"],
                    ),
                    (6, 18, "reported"),
                )
        self.assertEqual([r["reasoning_effort"] for r in requests], ["high", "low"])
        self.assertNotIn("stream", requests[1])
        self.assertEqual(
            requests[1]["messages"][1],
            {"role": "assistant", "content": "answer", "reasoning_content": "سابق"},
        )
        self.assertEqual(Account.objects.get(user=self.user).tokens_used, 36)
        _, jobs = reserve_turn(self.user, self.chat, "next", [self.model.pk])
        bound = Message.objects.get(pk=jobs[0].reply_id).input_bound
        self.assertEqual(
            bound,
            32
            + sum(
                32
                + len(m["content"].encode())
                + len(m.get("reasoning_content", "").encode())
                for m in jobs[0].messages
            ),
        )
        other = get_user_model().objects.create_user("other")
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_store_live_and_hidden_policies(self):
        for policy in ("store", "live", "hidden"):
            self.model.reasoning_policy = policy
            self.model.save()
            seen = []

            def handle(request):
                seen.append(json.loads(request.content)["messages"])
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": "yes",
                                    "reasoning_content": "trace",
                                }
                            }
                        ]
                    },
                )

            with upstream(handle):
                response = self.client.post(self.url, self.payload, format="json")
            self.assertEqual(response.status_code, 200)
            reply = response.data["messages"][-1]
            self.assertEqual(
                reply["reasoning_content"], "trace" if policy == "store" else None
            )
            self.assertEqual(reply["usage_source"], "estimated")
            self.assertIsNone(reply["reasoning_tokens"])
            self.assertTrue(all("reasoning_content" not in m for m in seen[0]))

    def test_preserve_does_not_replay_to_a_reconfigured_endpoint_or_another_model(self):
        _, jobs = reserve_turn(self.user, self.chat, "first", [self.model.pk])
        finish_reply(jobs[0].reply_id, "completed", "answer", None, "", "private", 7)
        self.model.model_id = "new-version"
        self.model.save()
        with self.assertRaises(ValidationError):
            reserve_turn(self.user, self.chat, "q", [self.model.pk])
        self.model.pk = None
        # A pre-discovery alias may share an upstream ID but keeps its own history.
        self.model.legacy_alias = True
        self.model.save()
        _, jobs = reserve_turn(self.user, self.chat, "q", [self.model.pk])
        self.assertEqual(jobs[0].messages, [{"role": "user", "content": "q"}])

    def test_reasoning_only_length_records_partial_and_total_without_split(self):
        with upstream(
            lambda _: httpx.Response(
                200,
                json={
                    "usage": {"total_tokens": 31},
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "reasoning_content": "partial",
                            },
                            "finish_reason": "length",
                        }
                    ],
                },
            )
        ):
            result = self.client.post(self.url, self.payload, format="json")
        reply = result.data["messages"][-1]
        self.assertEqual(
            (reply["status"], reply["total_tokens"], reply["reasoning_content"]),
            ("failed", 31, "partial"),
        )
        self.assertEqual(
            (reply["input_tokens"], reply["output_tokens"], reply["reasoning_tokens"]),
            (None, None, None),
        )
        self.assertEqual(Account.objects.get(user=self.user).tokens_used, 31)
        self.assertEqual(ModelUsage.objects.get().unsplit_tokens, 31)
        _, jobs = reserve_turn(self.user, self.chat, "retry", [self.model.pk])
        self.assertEqual(len(jobs[0].messages), 1)

    def test_partial_usage_retains_valid_fields_and_error_receipts(self):
        receipts = [
            {
                "choices": [{"message": {"content": "abc"}}],
                "usage": {
                    "prompt_tokens": 18,
                    "completion_tokens_details": {"reasoning_tokens": 2},
                },
            },
            {"error": {"message": "private error"}, "usage": {"completion_tokens": 7}},
        ]
        with upstream(lambda req: httpx.Response(200, json=receipts.pop(0))):
            first = self.client.post(self.url, self.payload, format="json").data[
                "messages"
            ][-1]
            second = self.client.post(self.url, self.payload, format="json").data[
                "messages"
            ][-1]
        self.assertEqual(
            (
                first["input_tokens"],
                first["output_tokens"],
                first["reasoning_tokens"],
                first["total_tokens"],
                first["usage_source"],
            ),
            (18, 5, 2, 23, "estimate_out"),
        )
        self.assertEqual(
            (
                second["input_tokens"],
                second["output_tokens"],
                second["total_tokens"],
                second["usage_source"],
                second["status"],
            ),
            (None, 7, None, "partial", "failed"),
        )
        self.assertEqual(Account.objects.get(user=self.user).tokens_used, 30)

    def test_admin_capabilities_and_contracts(self):
        for contract, levels in {
            "effort": ["low", "high"],
            "always": ["on"],
            "toggle": ["off", "on"],
            "toggle_effort": ["off", "low", "max"],
        }.items():
            self.model.thinking_contract = contract
            self.model.thinking_levels = levels
            self.model.thinking_default = levels[0]
            self.model.full_clean()
        self.assertEqual(
            parameters("toggle_effort", "off"), {"thinking": {"type": "disabled"}}
        )
        self.assertEqual(
            parameters("toggle_effort", "max"),
            {"thinking": {"type": "enabled"}, "reasoning_effort": "max"},
        )
        self.assertEqual(parameters("always", "on"), {})
        self.assertEqual(
            parameters("kimi_preserved", "low"),
            {"thinking": {"type": "enabled", "effort": "low", "keep": "all"}},
        )
        self.model.thinking_contract = "effort"
        with self.assertRaises(ConfigurationError):
            self.model.full_clean()
        self.model.thinking_contract = "toggle_effort"
        self.model.provider_output_limit = 100
        self.model.save()
        with self.assertRaises(ValidationError):
            reserve_turn(self.user, self.chat, "q", [self.model.pk])


class ThinkingWireTests(SimpleTestCase):
    async def test_chunk_separation_and_model_specific_output_parameter(self):
        model = connection_model()
        model.connection.api_key_env = ""
        model.reasoning_policy = "live"
        model.thinking_contract = "effort"
        model.thinking_levels = ["low"]
        model.output_parameter = "max_completion_tokens"
        model.stream_usage_option = False

        def respond(request):
            wire = json.loads(request.content)
            self.assertNotIn("stream_options", wire)
            self.assertNotIn("thinking", wire)
            self.assertNotIn("max_tokens", wire)
            self.assertEqual(
                (wire["reasoning_effort"], wire["max_completion_tokens"]), ("low", 123)
            )
            frames = [
                sse({"choices": [{"delta": {field: text}}]})
                for field, text in [
                    ("reasoning_content", "یک"),
                    ("reasoning_content", "دو"),
                    ("content", "سه"),
                    ("content", "چهار"),
                ]
            ]
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b"".join(frames) + b"data: [DONE]\n\n",
            )

        with mock_http(respond):
            events = [
                e
                async for e in stream_complete(
                    model, [{"role": "user", "content": "q"}], "low"
                )
            ]
        self.assertEqual(
            [(e.kind, e.text) for e in events],
            [
                ("reasoning_delta", "یک"),
                ("reasoning_delta", "دو"),
                ("delta", "سه"),
                ("delta", "چهار"),
                ("done", ""),
            ],
        )

    async def test_reject_oversize_chunk_without_newline(self):
        model = connection_model()
        model.connection.api_key_env = ""
        with (
            patch("portal.providers.MAX_EVENT_CHARS", 64),
            mock_http(
                lambda _: httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=b"data:" + b"x" * 100,
                )
            ),
            self.assertRaises(ProviderError) as err,
        ):
            _ = [e async for e in stream_complete(model, [])]
        self.assertEqual(err.exception.code, "response_limit")

    def test_usage_details_are_a_subset(self):
        self.assertEqual(
            parse_usage(
                {
                    "input_tokens": 2,
                    "output_tokens": 8,
                    "output_tokens_details": {"reasoning_tokens": 5},
                }
            ),
            Usage(2, 8, 10, 5),
        )
        self.assertEqual(
            parse_usage(
                {
                    "input_tokens": 2,
                    "output_tokens": 8,
                    "completion_tokens_details": {"reasoning_tokens": 20},
                }
            ),
            Usage(2, 8, 10, None),
        )
        self.assertIsNone(parse_usage({"total_tokens": 3, "prompt_tokens": 4}))

    @skipUnless(find_spec("tokenizers"), "optional offline tokenizer package")
    def test_offline_tokenizer_uses_local_ids_with_truncation_disabled(self):
        from tokenizers import Tokenizer, models, pre_tokenizers

        with (
            TemporaryDirectory() as directory,
            patch.dict(os.environ, {"LLM_TOKENIZER_DIR": directory}),
        ):
            tokenizer = Tokenizer(
                models.WordLevel({"[UNK]": 0, "abc": 1}, unk_token="[UNK]")
            )
            tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
            tokenizer.enable_truncation(1)
            tokenizer.save(str(Path(directory) / "verified.json"))
            self.assertEqual(input_counter("verified")("abc abc abc"), 3)
            with self.assertRaises(ValidationError):
                input_counter("../escape")
