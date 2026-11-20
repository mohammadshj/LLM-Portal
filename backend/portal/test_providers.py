import asyncio
import json
import os
from contextlib import aclosing, contextmanager
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings

from .models import LanguageModel, ModelConnection
from .providers import ProviderError, stream_complete

MESSAGES = [{"role": "user", "content": "private patient input"}]


@contextmanager
def mock_http(handler):
    cls = httpx.AsyncClient
    with patch(
        "portal.providers.httpx.AsyncClient",
        side_effect=lambda **kwargs: cls(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    ):
        yield


def connection_model():
    conn = ModelConnection(
        pk=4,
        base_url="https://provider.example/private/v1",
        api_key_env="LLM_FIRST_API_KEY",
    )
    # Explicit runtime capability for testing independent of migration state.
    conn.streaming_enabled = True
    return LanguageModel(
        pk=11,
        name="Test",
        provider="openai",
        model_id="configured-id",
        connection=conn,
        max_output_tokens=123,
    )


def sse(data):
    return ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode()


class ControlledStream(httpx.AsyncByteStream):
    """Mock an upstream that blocks after its first visible delta until released."""

    def __init__(self):
        self.release = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        yield b": heartbeat\r\n\r\n"
        yield sse(
            {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "reasoning_content": "hidden chain",
                        }
                    }
                ]
            }
        )
        payload = sse({"choices": [{"delta": {"content": "سلام"}}]})
        split = payload.index("س".encode()) + 1
        yield payload[:split]
        yield payload[split:]
        await self.release.wait()
        yield sse({"choices": [{"delta": {"content": "!"}, "finish_reason": "stop"}]})
        yield sse(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 11,
                    "prompt_cache_hit_tokens": 3,
                    "completion_tokens_details": {"reasoning_tokens": 8},
                },
            }
        )
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed = True


class ProviderTests(SimpleTestCase):
    def setUp(self):
        self.model = connection_model()
        keys = patch.dict(
            os.environ,
            {
                "LLM_FIRST_API_KEY": "private-first",
                "LLM_SECOND_API_KEY": "private-second",
            },
        )
        keys.start()
        self.addCleanup(keys.stop)

    async def read(self, handler):
        with mock_http(handler):
            return [e async for e in stream_complete(self.model, MESSAGES)]

    async def test_visible_delta_precedes_finish_and_reasoning_is_not_exported(self):
        upstream = ControlledStream()

        def reply(request):
            self.assertEqual(request.headers["authorization"], "Bearer private-first")
            self.assertEqual(
                json.loads(request.content),
                {
                    "model": "configured-id",
                    "messages": MESSAGES,
                    "max_tokens": 123,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                },
            )
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream; charset=utf-8"},
                stream=upstream,
            )

        with mock_http(reply):
            async with aclosing(stream_complete(self.model, MESSAGES)) as stream:
                first = await anext(stream)
                self.assertEqual((first.kind, first.text), ("delta", "سلام"))
                self.assertFalse(upstream.release.is_set())
                upstream.release.set()
                rest = [e async for e in stream]
        self.assertEqual([e.kind for e in rest], ["delta", "usage", "done"])
        self.assertEqual((rest[1].input_tokens, rest[1].output_tokens), (5, 11))
        self.assertTrue(upstream.closed)

    async def test_cancel_during_read_closes_upstream(self):
        upstream = ControlledStream()

        def reply(request):
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=upstream
            )

        started = asyncio.Event()

        async def consume():
            async with aclosing(stream_complete(self.model, MESSAGES)) as stream:
                async for _ in stream:
                    started.set()

        with mock_http(reply):
            task = asyncio.create_task(consume())
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(upstream.closed)

    async def test_http_statuses_logged_as_safe_structured_data(self):
        for status in (400, 401, 429, 500):
            with (
                self.subTest(status=status),
                self.assertLogs("portal.providers", "WARNING") as logs,
                self.assertRaises(ProviderError) as caught,
            ):
                await self.read(
                    lambda _: httpx.Response(
                        status, text="secret upstream diagnostic body"
                    )
                )
            self.assertEqual(caught.exception.code, f"http_{status}")
            self.assertEqual(caught.exception.status, status)
            record = json.loads(logs.records[-1].getMessage())
            self.assertEqual(record["http_status"], status)
            self.assertEqual(record["model_pk"], 11)
            self.assertEqual(record["connection_pk"], 4)
            for private in (
                "secret upstream",
                "provider.example",
                "Authorization",
                "private-first",
                "private patient",
            ):
                self.assertNotIn(private, str(caught.exception) + logs.output[-1])

    async def test_timeout_connection_and_interrupted_transport_are_distinct(self):
        for failure, code in [
            (httpx.ConnectError, "connection"),
            (httpx.ReadTimeout, "timeout"),
            (httpx.RemoteProtocolError, "transport"),
        ]:

            def fail(request):
                raise failure("private details", request=request)

            with self.subTest(code=code), self.assertRaises(ProviderError) as error:
                await self.read(fail)
            self.assertEqual(error.exception.code, code)
            self.assertIsNone(error.exception.status)
            self.assertNotIn("private details", str(error.exception))

    @override_settings(LLM_TOTAL_TIMEOUT=0.02)
    async def test_total_deadline_closes_stalled_stream(self):
        stream = ControlledStream()
        with self.assertRaises(ProviderError) as caught:
            await self.read(
                lambda _: httpx.Response(
                    200, headers={"content-type": "text/event-stream"}, stream=stream
                )
            )
        self.assertEqual(caught.exception.code, "timeout")
        self.assertEqual(caught.exception.status, 200)
        self.assertTrue(stream.closed)

    async def test_no_duplicate_http_posts_for_fallback_json_and_shared_url_separate_keys(
        self,
    ):
        seen = []

        def handler(request):
            body = json.loads(request.content)
            seen.append(
                (str(request.url), body.get("stream"), request.headers["authorization"])
            )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "reasoning_content": "secret reasoning",
                                "content": [{"type": "text", "text": "final answer"}],
                            }
                        }
                    ],
                    "usage": {"input_tokens": 2, "output_tokens": 3},
                },
            )

        buffered = await self.read(handler)
        self.model.connection.streaming_enabled = False
        self.model.connection.api_key_env = "LLM_SECOND_API_KEY"
        direct = await self.read(handler)
        self.assertEqual(
            seen,
            [
                (
                    "https://provider.example/private/v1/chat/completions",
                    True,
                    "Bearer private-first",
                ),
                (
                    "https://provider.example/private/v1/chat/completions",
                    None,
                    "Bearer private-second",
                ),
            ],
        )
        self.assertEqual(buffered, direct)
        self.assertEqual(
            (direct[0].input_tokens, direct[0].output_tokens, direct[1].text),
            (2, 3, "final answer"),
        )

    async def test_usage_missing_incomplete_invalid_or_total_only_never_fabricated(
        self,
    ):
        for usage, expected in [
            (None, None),
            ({}, None),
            ({"total_tokens": 7}, None),
            ({"prompt_tokens": 2, "total_tokens": 7}, (2, 5)),
            ({"prompt_tokens": True, "completion_tokens": 1}, None),
            ({"prompt_tokens": -2, "completion_tokens": 1}, None),
        ]:
            with self.subTest(usage=usage):
                events = await self.read(
                    lambda _: httpx.Response(
                        200,
                        json={
                            "choices": [{"message": {"content": "ok"}}],
                            "usage": usage,
                        },
                    )
                )
                self.assertEqual(events[-1].kind, "done")
                self.assertIn("ok", [e.text for e in events])
                self.assertEqual(
                    [
                        (e.input_tokens, e.output_tokens)
                        for e in events
                        if e.kind == "usage"
                    ],
                    [] if expected is None else [expected],
                )

    async def test_invalid_body_reasoning_only_and_missing_choices_report_categories(
        self,
    ):
        for content, code in [
            (b"{broken", "invalid_json"),
            (b"[]", "invalid_envelope"),
            (b"{}", "invalid_choices"),
            (b'{"choices":[{}]}', "invalid_message"),
            (b'{"choices":[{"message":{"content":3}}]}', "invalid_content"),
            (b'{"choices":[{"message":{"content":""}}]}', "empty_answer"),
            (
                b'{"choices":[{"message":{"reasoning_content":"private reasoning"}}]}',
                "reasoning_only",
            ),
            (
                b'{"choices":[{"message":{"content":null},"finish_reason":"length"}],"usage":{"prompt_tokens":5,"completion_tokens":30}}',
                "output_limit",
            ),
        ]:
            with self.subTest(code=code), self.assertRaises(ProviderError) as caught:
                await self.read(lambda _: httpx.Response(200, content=content))
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.status, 200)
            if code == "output_limit":
                self.assertEqual(caught.exception.usage, (5, 30))

    async def test_incomplete_stream_retains_delivered_text_with_error_not_done(self):
        contents = sse({"choices": [{"delta": {"content": "partial"}}]})
        events = []
        with mock_http(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=contents
            )
        ):
            with self.assertRaises(ProviderError) as caught:
                async for event in stream_complete(self.model, MESSAGES):
                    events.append(event)
        self.assertEqual(caught.exception.code, "stream_incomplete")
        self.assertEqual([(e.kind, e.text) for e in events], [("delta", "partial")])
