"""Exercise the ASGI HTTP response incrementally, including an actual http.disconnect."""

import asyncio
import json
from collections import deque
from contextlib import AsyncExitStack, asynccontextmanager
from unittest.mock import patch
from uuid import uuid4

from asgiref.sync import sync_to_async
from asgiref.testing import ApplicationCommunicator
from django.contrib.auth import get_user_model
from django.core.asgi import get_asgi_application
from django.test import Client, TransactionTestCase

from .models import Account, Conversation, LanguageModel, Message, ModelConnection
from .providers import ProviderError, ProviderEvent


class SSEReader:
    """Read SSE data independently of ASGI body boundaries."""

    def __init__(self, communicator):
        self.communicator = communicator
        self.buffer = b""
        self.events = deque()

    async def until(self, event_type):
        # A stream sending only heartbeats must fail the test within a finite time.
        async with asyncio.timeout(12):
            while True:
                while self.events:
                    event = self.events.popleft()
                    if event["type"] == event_type:
                        return event
                packet = await self.communicator.receive_output(timeout=12)
                self.buffer += packet.get("body", b"")
                while b"\n\n" in self.buffer:
                    frame, self.buffer = self.buffer.split(b"\n\n", 1)
                    data = [
                        line[5:].strip()
                        for line in frame.splitlines()
                        if line.startswith(b"data:")
                    ]
                    if data:
                        self.events.append(json.loads(b"\n".join(data)))
                if not packet.get("more_body") and not self.events:
                    raise AssertionError(f"Stream ended before {event_type}")


class StreamHTTPTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("stream-user")
        self.other = get_user_model().objects.create_user("other-user")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.csrf = self.client.get("/api/auth/csrf/").json()["csrfToken"]
        self.models = [
            LanguageModel.objects.create(provider="demo", model_id=name, name=name)
            for name in ("fast", "medium", "slow")
        ]
        self.chats = [
            Conversation.objects.create(user=self.user, title=letter)
            for letter in ("A", "B", "C")
        ]

    def payload(self, chat, models=None):
        return {
            "request_id": str(uuid4()),
            "content": chat.title,
            "model_ids": [model.pk for model in (models or self.models[:1])],
        }

    def stream_url(self, chat):
        return f"/api/conversations/{chat.pk}/stream/"

    def cancel_url(self, chat, payload):
        return f"/api/conversations/{chat.pk}/requests/{payload['request_id']}/cancel/"

    @asynccontextmanager
    async def open_stream(self, chat, payload):
        body = json.dumps(payload).encode()
        headers = [
            (b"content-length", str(len(body)).encode()),
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"x-csrftoken", self.csrf.encode()),
            (
                b"cookie",
                "; ".join(
                    f"{key}={cookie.value}"
                    for key, cookie in self.client.cookies.items()
                ).encode(),
            ),
        ]
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": self.stream_url(chat),
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "headers": headers,
        }
        communicator = ApplicationCommunicator(get_asgi_application(), scope)
        try:
            await communicator.send_input({"type": "http.request", "body": body})
            response = await communicator.receive_output(timeout=10)
            self.assertEqual(response["type"], "http.response.start")
            self.assertEqual(response["status"], 200)
            headers = {key.lower(): val for key, val in response["headers"]}
            self.assertIn(b"text/event-stream", headers[b"content-type"])
            yield SSEReader(communicator)
        finally:
            if not communicator.future.done():
                await communicator.send_input({"type": "http.disconnect"})
            await communicator.wait(timeout=10)

    def test_stream_and_stop_require_session_csrf_and_ownership(self):
        chat = self.chats[0]
        payload = self.payload(chat)
        foreign_chat = Conversation.objects.create(user=self.other, title="private")
        routes = [self.stream_url, lambda c: self.cancel_url(c, payload)]
        anonymous = Client(enforce_csrf_checks=True)
        token = anonymous.get("/api/auth/csrf/").json()["csrfToken"]
        for route in routes:
            self.assertIn(
                anonymous.post(
                    route(chat),
                    data=payload,
                    content_type="application/json",
                    HTTP_X_CSRFTOKEN=token,
                ).status_code,
                (401, 403),
            )
            self.assertEqual(
                self.client.post(
                    route(chat), data=payload, content_type="application/json"
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.post(
                    route(foreign_chat),
                    data=payload,
                    content_type="application/json",
                    HTTP_X_CSRFTOKEN=self.csrf,
                ).status_code,
                404,
            )
        self.assertFalse(Message.objects.exists())

    async def test_admin_deactivation_stops_stream_even_after_immediate_reactivation(
        self,
    ):
        chat = self.chats[0]
        closed = asyncio.Event()

        async def provider(model, messages):
            try:
                yield ProviderEvent("usage", input_tokens=8, output_tokens=3)
                yield ProviderEvent("delta", text="بخش اول")
                await asyncio.Event().wait()
            finally:
                closed.set()

        def set_active(active):
            data = {"username": self.user.username, "role": "user"}
            if active:
                data["is_active"] = "on"
            return admin_client.post(
                f"/admin/auth/user/{self.user.pk}/change/", data
            ).status_code

        admin_client = Client()
        manager = await get_user_model().objects.acreate_superuser("manager")
        await admin_client.aforce_login(manager)
        with patch("portal.streaming.stream_complete", provider):
            async with self.open_stream(chat, self.payload(chat)) as stream:
                await stream.until("delta")
                self.assertEqual(await sync_to_async(set_active)(False), 302)
                self.assertEqual(
                    (await sync_to_async(self.client.get)("/api/auth/me/")).status_code,
                    403,
                )
                self.assertEqual(await sync_to_async(set_active)(True), 302)
                await asyncio.wait_for(closed.wait(), 5)
                await stream.until("done")
        reply = await Message.objects.aget(conversation=chat, role="assistant")
        self.assertEqual(
            (reply.status, reply.content, reply.total_tokens, reply.reserved_tokens),
            ("cancelled", "بخش اول", 11, 0),
        )
        self.assertEqual((await Account.objects.aget(user=self.user)).tokens_used, 11)

    async def test_three_active_chats_stop_one_idle_provider(self):
        gates = {chat.title: asyncio.Event() for chat in self.chats}
        closed = {chat.title: asyncio.Event() for chat in self.chats}

        async def provider(model, messages):
            title = messages[-1]["content"]
            try:
                yield ProviderEvent(kind="delta", text=f"{title}...")
                await gates[title].wait()
                yield ProviderEvent(kind="delta", text="end")
                yield ProviderEvent(kind="usage", input_tokens=7, output_tokens=2)
                yield ProviderEvent(kind="done")
            finally:
                closed[title].set()

        with patch("portal.streaming.stream_complete", provider):
            async with AsyncExitStack() as stack:
                streams, payloads = {}, {}
                for chat in self.chats:
                    payload = self.payload(chat)
                    payloads[chat.title] = payload
                    stream = await stack.enter_async_context(
                        self.open_stream(chat, payload)
                    )
                    streams[chat.title] = stream
                    first = await stream.until("delta")
                    self.assertEqual(
                        (first["conversation_id"], first["request_id"], first["text"]),
                        (chat.pk, payload["request_id"], f"{chat.title}..."),
                    )
                # No provider has been allowed to finish. All three HTTP requests
                # already delivered visible text, proving overlap across a single user.
                middle = self.chats[1]
                response = await sync_to_async(self.client.post)(
                    self.cancel_url(middle, payloads["B"]),
                    data={},
                    content_type="application/json",
                    HTTP_X_CSRFTOKEN=self.csrf,
                )
                self.assertIn(response.status_code, (200, 202, 204))
                await asyncio.wait_for(closed["B"].wait(), timeout=8)
                await streams["B"].until("done")
                self.assertFalse(closed["A"].is_set())
                self.assertFalse(closed["C"].is_set())
                for title in ("C", "A"):
                    gates[title].set()
                    await streams[title].until("done")

        for chat in self.chats:
            reply = await Message.objects.aget(conversation=chat, role="assistant")
            self.assertEqual(reply.reserved_tokens, 0)
            self.assertEqual(
                reply.content, f"{chat.title}..." + ("" if chat.title == "B" else "end")
            )
            self.assertEqual(
                reply.status, "cancelled" if chat.title == "B" else "completed"
            )
            if chat.title != "B":
                self.assertEqual((reply.input_tokens, reply.output_tokens), (7, 2))

    async def test_failed_turn_can_be_retried_without_polluting_model_context(self):
        chat, model = self.chats[0], self.models[0]
        payload = self.payload(chat)
        contexts = []

        async def unreliable_provider(selected, messages):
            contexts.append(messages)
            if len(contexts) == 1:
                raise ProviderError("خطای سرویس", code="http_503", status=503)
            yield ProviderEvent(kind="delta", text="جواب")
            yield ProviderEvent(kind="usage", input_tokens=4, output_tokens=2)
            yield ProviderEvent(kind="done")

        with patch("portal.streaming.stream_complete", unreliable_provider):
            async with self.open_stream(chat, payload) as stream:
                result = await stream.until("model_error")
                self.assertEqual(result["model_id"], model.pk)
                await stream.until("done")

            async with self.open_stream(chat, self.payload(chat)) as stream:
                await stream.until("model_done")
                await stream.until("done")

        expected = [{"role": "user", "content": payload["content"]}]
        self.assertEqual(contexts, [expected, expected])
        rows = [
            row
            async for row in Message.objects.filter(
                conversation=chat, role="assistant"
            ).order_by("id")
        ]
        self.assertEqual([row.status for row in rows], ["failed", "completed"])
        self.assertEqual([row.reserved_tokens for row in rows], [0, 0])
        self.assertTrue(rows[0].error)

    async def test_http_disconnect_closes_upstream_and_releases_partial_reply(self):
        closed = asyncio.Event()

        async def stalled(model, messages):
            try:
                yield ProviderEvent(kind="delta", text="متن اولیه")
                await asyncio.Event().wait()
            finally:
                closed.set()

        chat = self.chats[0]
        with patch("portal.streaming.stream_complete", stalled):
            async with self.open_stream(chat, self.payload(chat)) as stream:
                delta = await stream.until("delta")
                self.assertEqual(delta["text"], "متن اولیه")
            # open_stream sent http.disconnect; no explicit Stop POST.
            await asyncio.wait_for(closed.wait(), timeout=5)
        row = await Message.objects.aget(conversation=chat, role="assistant")
        self.assertEqual(
            (row.status, row.content, row.reserved_tokens),
            ("cancelled", "متن اولیه", 0),
        )

    async def test_disconnect_during_reasoning_persists_partial_without_inventing_usage(
        self,
    ):
        chat, model = self.chats[0], self.models[0]
        model.connection = await ModelConnection.objects.acreate(
            name="reason", base_url="https://reason.example/v1", api_key_env=""
        )
        model.provider = "openai"
        model.thinking_contract = "always"
        model.thinking_levels = ["on"]
        model.thinking_default = "on"
        model.reasoning_policy = "store"
        await model.asave()
        closed = asyncio.Event()

        async def stalled(selected, messages, level):
            self.assertEqual(level, "on")
            try:
                yield ProviderEvent("reasoning_delta", text="نیمه")
                await asyncio.Event().wait()
            finally:
                closed.set()

        with patch("portal.streaming.stream_complete", stalled):
            async with self.open_stream(chat, self.payload(chat)) as stream:
                self.assertEqual(
                    (await stream.until("reasoning_delta"))["text"], "نیمه"
                )
            await asyncio.wait_for(closed.wait(), timeout=5)
        reply = await Message.objects.aget(conversation=chat, role="assistant")
        self.assertEqual(
            (
                reply.status,
                reply.content,
                reply.reasoning_content,
                reply.reserved_tokens,
            ),
            ("cancelled", "", "نیمه", 0),
        )
        self.assertEqual(
            (reply.usage_source, reply.reasoning_tokens), ("estimated", None)
        )
        self.assertEqual(
            (await Account.objects.aget(user=self.user)).tokens_used, reply.total_tokens
        )

    async def test_three_models_stream_independently_into_one_turn(self):
        started = {model.pk: asyncio.Event() for model in self.models}
        gates = {model.pk: asyncio.Event() for model in self.models}

        async def provider(model, messages):
            started[model.pk].set()
            await gates[model.pk].wait()
            yield ProviderEvent(kind="delta", text=model.name)
            yield ProviderEvent(kind="usage", input_tokens=10, output_tokens=3)
            yield ProviderEvent(kind="done")

        chat = self.chats[0]
        with patch("portal.streaming.stream_complete", provider):
            async with self.open_stream(
                chat, self.payload(chat, self.models)
            ) as stream:
                await asyncio.wait_for(
                    asyncio.gather(*(event.wait() for event in started.values())),
                    timeout=5,
                )
                for model in reversed(self.models):
                    gates[model.pk].set()
                    event = await stream.until("delta")
                    self.assertEqual(
                        (event["model_id"], event["text"]), (model.pk, model.name)
                    )
                    await stream.until("model_done")
                await stream.until("done")
        rows = [
            m async for m in Message.objects.filter(conversation=chat, role="assistant")
        ]
        self.assertCountEqual([m.content for m in rows], ["fast", "medium", "slow"])
        self.assertTrue(
            all(
                (m.status, m.input_tokens, m.output_tokens, m.reserved_tokens)
                == ("completed", 10, 3, 0)
                for m in rows
            )
        )
