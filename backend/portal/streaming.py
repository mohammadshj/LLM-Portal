"""Merge up to three independent provider streams, with bounded backpressure."""

import asyncio
import json
import logging
from contextlib import aclosing
from dataclasses import dataclass, field
from io import StringIO

from asgiref.sync import async_to_sync, sync_to_async
from django.http import StreamingHttpResponse
from django.utils import timezone

from .providers import ProviderError, stream_complete
from .services import finish_reply, reserve_turn, should_cancel
from .tokens import Usage

logger = logging.getLogger(__name__)
POLL_SECONDS = 0.75
KEEPALIVE_SECONDS = 8


@dataclass
class Progress:
    # Buffers are request-local. Live-only reasoning contributes a byte count.
    answer: StringIO = field(default_factory=StringIO)
    reasoning: StringIO | None = None
    reasoning_bytes: int = 0
    visible_bytes: int = 0
    usage: Usage | None = None


class TurnStream:
    def __init__(self, turn, jobs):
        self.turn = turn
        self.jobs = jobs
        self.started = False
        self.closing = False

    def frame(self, payload):
        payload.update(
            request_id=str(self.turn.request_id),
            conversation_id=self.turn.conversation_id,
        )
        return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode()

    async def emit(self, job, kind, **data):
        if not self.closing:
            await self.queue.put(
                dict(
                    type=kind, model_id=job.model.pk, model_name=job.model.name, **data
                )
            )

    async def read_provider(self, job, progress):
        # All reads and aclose() for one HTTP response run in the same task.
        stream = (
            stream_complete(job.model, job.messages, job.thinking_level)
            if job.thinking_level
            else stream_complete(job.model, job.messages)
        )
        async with aclosing(stream) as source:
            async for event in source:
                if event.kind in ("delta", "reasoning_delta"):
                    size = len(event.text.encode())
                    if progress.visible_bytes + size > 4 * 1024 * 1024:
                        raise ProviderError(
                            "حجم متن مدل از حد مجاز گذشت.", code="text_limit"
                        )
                    progress.visible_bytes += size
                    if event.kind == "delta":
                        progress.answer.write(event.text)
                    else:
                        progress.reasoning_bytes += size
                        if job.model.reasoning_policy in ("store", "preserve"):
                            if progress.reasoning is None:
                                progress.reasoning = StringIO()
                            progress.reasoning.write(event.text)
                    await self.emit(job, event.kind, text=event.text)
                elif event.kind == "usage":
                    total = event.total_tokens
                    if (
                        total is None
                        and event.input_tokens is not None
                        and event.output_tokens is not None
                    ):
                        total = event.input_tokens + event.output_tokens
                    progress.usage = Usage(
                        event.input_tokens,
                        event.output_tokens,
                        total,
                        event.reasoning_tokens,
                    )
                elif event.kind == "done":
                    return
        raise RuntimeError("provider iterator ended without done")

    async def settle(self, job, reader, progress):
        # Only the HTTP reader is cancelled. Its settlement task always runs,
        # including when the reader was cancelled before its first instruction.
        status, error = "completed", ""
        try:
            await reader
        except asyncio.CancelledError:
            status = "cancelled"
        except ProviderError as exc:
            status, error = "failed", str(exc)
            if exc.usage is not None:
                progress.usage = exc.usage
        except Exception as exc:
            status = "failed"
            error = "در پردازش پاسخ مدل خطایی رخ داد."
            logger.error(
                "stream_reader_failed",
                extra={"reply_id": job.reply.pk, "error_class": type(exc).__name__},
            )

        # Database failure terminates this stream; the lease covers uncommitted work.
        status, elapsed_ms = await sync_to_async(finish_reply)(
            job.reply.pk,
            status,
            progress.answer.getvalue(),
            progress.usage,
            error,
            progress.reasoning.getvalue() if progress.reasoning is not None else None,
            progress.reasoning_bytes,
            finished_at=timezone.now(),
        )
        await self.emit(
            job,
            "model_error" if status == "failed" else "model_done",
            status=status,
            detail=error,
            elapsed_ms=elapsed_ms,
            usage=(
                {
                    "input_tokens": progress.usage.incoming,
                    "output_tokens": progress.usage.outgoing,
                    "reasoning_tokens": progress.usage.reasoning,
                    "total_tokens": progress.usage.total,
                    "usage_source": "reported",
                }
                if progress.usage and progress.usage.total is not None
                else None
            ),
        )

    async def watch_cancel(self, readers):
        try:
            while not await sync_to_async(should_cancel)(self.turn.pk):
                await asyncio.sleep(POLL_SECONDS)
        finally:
            # The flag lives in PostgreSQL. A Stop handled by a different worker
            # interrupts even a provider blocked waiting for its first byte.
            for reader in readers:
                reader.cancel()

    async def events(self):
        self.started = True
        self.queue = asyncio.Queue(maxsize=32)
        readers, writers = [], []
        pending_event = watcher = settled = None
        try:
            # The UUID and reservations already exist when this frame is delivered.
            yield {"type": "start"}
            for job in self.jobs:
                yield (
                    {
                        "type": "model_start",
                        "elapsed_ms": job.reply.elapsed_ms(),
                        "model_id": job.model.pk,
                        "model_name": job.model.name,
                    }
                )
            stopped = await sync_to_async(should_cancel)(self.turn.pk)
            for job in self.jobs:
                progress = Progress()
                reader = asyncio.create_task(self.read_provider(job, progress))
                readers.append(reader)
                if stopped:
                    reader.cancel()
                writers.append(asyncio.create_task(self.settle(job, reader, progress)))
            watcher = asyncio.create_task(self.watch_cancel(readers))
            settled = asyncio.gather(*writers)
            # Every producer awaits queue.put when the browser/network is slow.
            # Wait on completion too: a failed DB write must not hang the reader.
            while not settled.done() or not self.queue.empty():
                pending_event = asyncio.create_task(self.queue.get())
                while not pending_event.done():
                    ready, _ = await asyncio.wait(
                        (pending_event, settled),
                        timeout=KEEPALIVE_SECONDS,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if settled in ready:
                        settled.result()
                        if not pending_event.done() and self.queue.empty():
                            break
                    if not ready:
                        yield {"type": "ping"}
                if pending_event.done():
                    yield pending_event.result()
                else:
                    pending_event.cancel()
                    await asyncio.gather(pending_event, return_exceptions=True)
            await settled
            yield {"type": "done"}
        finally:
            self.closing = True
            for task in [*readers, watcher, pending_event]:
                if task is not None and not task.done():
                    task.cancel()
            # Free slots for up to three final events already waiting in emit().
            while not self.queue.empty():
                self.queue.get_nowait()
            tasks = [
                t for t in [*writers, watcher, pending_event, settled] if t is not None
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            # Stop/disconnect can precede creation of any provider tasks.
            for job in self.jobs[len(writers) :]:
                await sync_to_async(finish_reply)(job.reply.pk, "cancelled")

    async def frames(self):
        async with aclosing(self.events()) as events:
            async for event in events:
                yield self.frame(event)

    async def collect_errors(self):
        errors = []
        async with aclosing(self.events()) as events:
            async for event in events:
                if event["type"] == "model_error":
                    errors.append(
                        {"model": event["model_name"], "detail": event["detail"]}
                    )
        return errors

    def close_unstarted(self):
        if not self.started:
            for job in self.jobs:
                finish_reply(job.reply.pk, "cancelled")


class EventStreamResponse(StreamingHttpResponse):
    def __init__(self, stream):
        self.stream = stream
        self.frames = stream.frames()
        super().__init__(self.frames, content_type="text/event-stream; charset=utf-8")
        self["Cache-Control"] = "no-cache, no-store, no-transform"
        self["X-Accel-Buffering"] = "no"

    def __aiter__(self):
        # Django's ASGI handler explicitly closes this iterator on disconnect.
        # Returning the actual generator ensures its finally block is awaited.
        return self.frames

    def close(self):
        try:
            self.stream.close_unstarted()
        finally:
            super().close()


def send_message(
    user, conversation, content, model_ids, request_id=None, thinking=None
):
    """Original JSON API, using the same cancellation, deadlines and accounting as SSE."""
    turn, jobs = reserve_turn(
        user, conversation, content, model_ids, request_id, thinking
    )
    for job in jobs:
        if job.model.connection is not None:
            # Preserve the legacy upstream JSON contract on these request-local objects.
            job.model.connection.streaming_enabled = False
    return async_to_sync(TurnStream(turn, jobs).collect_errors)()
