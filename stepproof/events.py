"""Typed event bus. Producer: the agent/session threads. Consumer: FastAPI SSE + tests.
Events are small JSON-able dicts: {"ts", "type", "data"}. No model calls ever touch this file."""
from __future__ import annotations
import json, queue, threading, time
from typing import Iterator


class EventBus:
    def __init__(self, maxlen: int = 2000) -> None:
        self._lock = threading.Lock()
        self._subs: list[queue.Queue[dict]] = []
        self._log: list[dict] = []
        self._maxlen = maxlen

    def publish(self, type_: str, data: dict | None = None) -> None:
        ev = {"ts": round(time.time(), 3), "type": type_, "data": data or {}}
        with self._lock:
            self._log.append(ev)
            if len(self._log) > self._maxlen:
                self._log.pop(0)
            for q in self._subs:
                q.put_nowait(ev)

    def subscribe(self) -> queue.Queue[dict]:
        q: queue.Queue[dict] = queue.Queue()
        with self._lock:
            self._subs.append(q)
        return q

    def history(self) -> list[dict]:
        with self._lock:
            return list(self._log)

    def sse_stream(self, since: int = 0) -> Iterator[str]:
        """SSE generator: replay events after index `since`, then live. One thread at a time."""
        q = self.subscribe()
        with self._lock:
            start = max(0, min(since, len(self._log)))
            for ev in self._log[start:]:
                yield f"data: {json.dumps(ev)}\n\n"
        while True:
            ev = q.get()
            yield f"data: {json.dumps(ev)}\n\n"

    def reset(self) -> None:
        with self._lock:
            self._log.clear()
            self._subs.clear()


BUS = EventBus()
