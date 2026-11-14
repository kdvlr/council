import asyncio
import json
import time
from typing import Any, AsyncIterator, Callable, Coroutine, Optional


class RunEventStream:
    """Pub/sub event stream for a single running deliberation job."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.subscribers: set[asyncio.Queue[Optional[dict[str, Any]]]] = set()
        self.history: list[dict[str, Any]] = []
        self.task: Optional[asyncio.Task[None]] = None
        self._has_finished = False
        self.created_monotonic = time.monotonic()

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        msg = {"event": event_type, "data": payload}
        # Keep non-token structural events + bounded recent history so late joiners catch up
        if event_type != "token" or len(self.history) < 2500:
            self.history.append(msg)
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def mark_finished(self) -> bool:
        """Single-advancement guard: returns True only on the first terminal transition."""
        if self._has_finished:
            return False
        self._has_finished = True
        for q in list(self.subscribers):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        return True


class JobManager:
    def __init__(self) -> None:
        self._streams: dict[str, RunEventStream] = {}

    def get_stream(self, run_id: str) -> Optional[RunEventStream]:
        return self._streams.get(run_id)

    def start_job(
        self,
        run_id: str,
        runner_factory: Callable[[RunEventStream], Coroutine[Any, Any, None]],
    ) -> RunEventStream:
        stream = RunEventStream(run_id)
        self._streams[run_id] = stream

        async def _wrapped() -> None:
            try:
                await runner_factory(stream)
            finally:
                stream.mark_finished()
                # Retain completed stream briefly for late SSE handshakes, then GC
                await asyncio.sleep(60)
                self._streams.pop(run_id, None)

        stream.task = asyncio.create_task(_wrapped())
        return stream

    def cancel_job(self, run_id: str) -> bool:
        stream = self._streams.get(run_id)
        if not stream or not stream.task or stream.task.done():
            return False
        stream.task.cancel()
        return True

    async def subscribe_sse(self, run_id: str) -> AsyncIterator[str]:
        stream = self._streams.get(run_id)
        if not stream:
            yield f"event: done\ndata: {json.dumps({'run_id': run_id, 'cached': True})}\n\n"
            return

        queue: asyncio.Queue[Optional[dict[str, Any]]] = asyncio.Queue(maxsize=4096)
        # Replay structural / buffered events then subscribe live
        snapshot = list(stream.history)
        if not stream._has_finished:
            stream.subscribers.add(queue)

        try:
            for item in snapshot:
                yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"

            if stream._has_finished:
                return

            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue

                if msg is None:
                    break
                yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
        finally:
            stream.subscribers.discard(queue)


job_manager = JobManager()
