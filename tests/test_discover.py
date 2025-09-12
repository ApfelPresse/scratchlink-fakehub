import json
from pathlib import Path

import pytest

from conftest import FakeWebSocket
from scratchlink_fakehub.device import FakeDevice
from tests.scratch_fake import parse_log_file, ScratchFakeRunner

DISCOVER_LOG = "debug_message_discover.json"


def _load_steps(name: str):
    base = Path(__file__).resolve().parent / "data"
    path = base / name
    assert path.exists(), f"Log file not found: {path}"
    return parse_log_file(path)


@pytest.mark.asyncio
async def test_discover_from_log():
    steps = _load_steps(DISCOVER_LOG)

    d = FakeDevice()
    ws = FakeWebSocket(incoming=[])

    await ScratchFakeRunner(d, ws).play(steps)

    assert any(s.direction == "in" and s.obj and s.obj.get("method") == "discover" for s in steps), \
        "No discover request found in the log"

    sent = [json.loads(m) for m in ws.sent]
    discovered = [m for m in sent if m.get("method") == "didDiscoverPeripheral"]
    assert discovered, "didDiscoverPeripheral not emitted"

    params = discovered[0].get("params", {})
    assert params.get("peripheralId"), "peripheralId missing/empty in didDiscoverPeripheral"

    ack_discover = [m for m in sent if "result" in m and isinstance(m.get("id"), int)]
    assert ack_discover, "ACK for discover missing"
