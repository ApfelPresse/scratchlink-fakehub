import asyncio
import base64
import json

import pytest


def b64_to_bytes(s: str) -> bytes:
    return base64.b64decode(s) if s else b""


def last_json(sent):
    assert sent, "No messages were sent"
    return json.loads(sent[-1])


def all_json(sent):
    return [json.loads(m) for m in sent]


class FakeWebSocket:
    # Minimal test double for a websockets connection.
    # - Accepts a list of incoming JSON-serializable messages (dicts) or raw JSON strings.
    # - Captures all outgoing messages via `send`.
    # - Supports `async for` iteration.
    def __init__(self, incoming=None):
        self._incoming = list(incoming or [])
        for i, m in enumerate(self._incoming):
            if isinstance(m, dict):
                self._incoming[i] = json.dumps(m)
        self.sent = []
        self._idx = 0

    async def send(self, payload: str):
        assert isinstance(payload, str), "send() must be called with a JSON string"
        self.sent.append(payload)

    def __aiter__(self):
        self._idx = 0
        return self

    async def __anext__(self):
        if self._idx >= len(self._incoming):
            raise StopAsyncIteration
        item = self._incoming[self._idx]
        self._idx += 1
        await asyncio.sleep(0)
        return item


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SL_HEARTBEAT_HZ", "20")
    yield
