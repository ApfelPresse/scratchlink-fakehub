import asyncio
import base64
import json

import pytest

from scratchlink_fakehub.microbit import (
    MicrobitDevice,
    UUID,
    TILT_MAG,
    GESTURE_NONE,
    GESTURE_MOVED,
    GESTURE_SHAKEN,
    GESTURE_JUMPED,
    OP_DISPLAY_TXT,
    OP_DISPLAY_5x5,
    OP_SET_PIXEL,
)


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data: str):
        self.sent.append(json.loads(data))


def last_notif(ws: FakeWS):
    for msg in reversed(ws.sent):
        if msg.get("method") == "characteristicDidChange":
            return msg
    return None


def all_notifs(ws: FakeWS):
    return [m for m in ws.sent if m.get("method") == "characteristicDidChange"]


def decode_b64_message(msg):
    b64 = msg["params"]["message"]
    return base64.b64decode(b64)


class CapturingMicrobit(MicrobitDevice):
    def __init__(self):
        super().__init__()
        self.display_events = []

    async def on_display_text(self, text: str):
        self.display_events.append(("text", text))

    async def on_display_matrix(self, rows):
        self.display_events.append(("matrix", list(rows[:5])))

    async def on_clear_display(self):
        self.display_events.append(("clear", None))

    async def on_set_pixel(self, x: int, y: int, on: bool):
        self.display_events.append(("pixel", (x, y, bool(on))))


pytestmark = pytest.mark.asyncio


async def start_rx(device: MicrobitDevice, ws: FakeWS):
    device.ws = ws
    await device.read(
        ws, msg_id=1,
        params={"startNotifications": True, "serviceId": UUID.SVC_ID, "characteristicId": UUID.CHAR_RX}
    )
    await asyncio.sleep(0.01)


async def stop_rx(device: MicrobitDevice):
    device._rx_enabled = False
    if device._hb_task:
        device._hb_task.cancel()
        device._hb_task = None


async def test_start_notifications_sends_initial_snapshot():
    dev = MicrobitDevice()
    ws = FakeWS()
    await start_rx(dev, ws)

    assert dev._rx_enabled is True

    msg = last_notif(ws)
    assert msg is not None
    payload = decode_b64_message(msg)
    assert isinstance(payload, (bytes, bytearray))
    assert len(payload) == 10

    assert payload[4:9] == b"\x00\x00\x00\x00\x00"
    assert payload[9] == GESTURE_NONE

    await stop_rx(dev)


async def test_press_release_buttons_update_snapshot():
    dev = MicrobitDevice()
    ws = FakeWS()
    await start_rx(dev, ws)

    await dev.press_a()
    await asyncio.sleep(0.01)
    pa = decode_b64_message(last_notif(ws))
    assert pa[4] == 1
    assert pa[5] == 0

    await dev.release_a()
    await asyncio.sleep(0.01)
    ra = decode_b64_message(last_notif(ws))
    assert ra[4] == 0

    await dev.press_b()
    await asyncio.sleep(0.01)
    pb = decode_b64_message(last_notif(ws))
    assert pb[5] == 1

    await dev.release_b()
    await asyncio.sleep(0.01)
    rb = decode_b64_message(last_notif(ws))
    assert rb[5] == 0

    await stop_rx(dev)


async def test_gestures_mapping_and_clear():
    dev = MicrobitDevice()
    ws = FakeWS()
    await start_rx(dev, ws)

    await dev.moved()
    await asyncio.sleep(0.01)
    pm = decode_b64_message(last_notif(ws))
    assert pm[9] == GESTURE_MOVED

    await dev.shaken()
    await asyncio.sleep(0.01)
    ps = decode_b64_message(last_notif(ws))
    assert ps[9] == GESTURE_SHAKEN

    await dev.jumped()
    await asyncio.sleep(0.01)
    pj = decode_b64_message(last_notif(ws))
    assert pj[9] == GESTURE_JUMPED

    await stop_rx(dev)


async def test_tilt_methods_write_int16_le():
    dev = MicrobitDevice()
    ws = FakeWS()
    await start_rx(dev, ws)

    await dev.tilt_front()
    await asyncio.sleep(0.01)
    pf = decode_b64_message(last_notif(ws))
    tiltX = (pf[0] << 8) | pf[1]
    tiltY = (pf[2] << 8) | pf[3]

    if tiltX & 0x8000: tiltX -= 0x10000
    if tiltY & 0x8000: tiltY -= 0x10000
    assert tiltX == 0
    assert tiltY == +TILT_MAG

    await dev.tilt_left()
    await asyncio.sleep(0.01)
    pl = decode_b64_message(last_notif(ws))
    tiltX = (pl[0] << 8) | pl[1]
    tiltY = (pl[2] << 8) | pl[3]
    if tiltX & 0x8000: tiltX -= 0x10000
    if tiltY & 0x8000: tiltY -= 0x10000
    assert tiltX == -TILT_MAG
    assert tiltY == 0

    await stop_rx(dev)


async def test_pin_connected_sets_bytes_6_8():
    dev = MicrobitDevice()
    ws = FakeWS()
    await start_rx(dev, ws)

    await dev.pin_connected(0, True)
    await asyncio.sleep(0.01)
    p0 = decode_b64_message(last_notif(ws))
    assert p0[6] == 1 and p0[7] == 0 and p0[8] == 0

    await dev.pin_connected(1, True)
    await asyncio.sleep(0.01)
    p1 = decode_b64_message(last_notif(ws))
    assert p1[6] == 1 and p1[7] == 1 and p1[8] == 0

    await dev.pin_connected(2, True)
    await asyncio.sleep(0.01)
    p2 = decode_b64_message(last_notif(ws))
    assert p2[6] == 1 and p2[7] == 1 and p2[8] == 1

    await dev.pin_connected(2, False)
    await asyncio.sleep(0.01)
    p2r = decode_b64_message(last_notif(ws))
    assert p2r[8] == 0

    await stop_rx(dev)


async def test_display_writes_are_dispatched_to_callbacks():
    dev = CapturingMicrobit()
    ws = FakeWS()
    dev.ws = ws

    payload = bytes([OP_DISPLAY_TXT]) + "Hello".encode("utf-8")
    await dev.write(ws, msg_id=10, params={
        "serviceId": UUID.SVC_ID,
        "characteristicId": UUID.CHAR_TX,
        "message": base64.b64encode(payload).decode("ascii"),
    })

    payload = bytes([OP_DISPLAY_5x5, 0x1F, 0x00, 0x00, 0x00, 0x00])
    await dev.write(ws, msg_id=11, params={
        "serviceId": UUID.SVC_ID,
        "characteristicId": UUID.CHAR_TX,
        "message": base64.b64encode(payload).decode("ascii"),
    })
    payload = bytes([OP_DISPLAY_5x5, 0, 0, 0, 0, 0])
    await dev.write(ws, msg_id=12, params={
        "serviceId": UUID.SVC_ID,
        "characteristicId": UUID.CHAR_TX,
        "message": base64.b64encode(payload).decode("ascii"),
    })

    payload = bytes([OP_SET_PIXEL, 2, 3, 1])
    await dev.write(ws, msg_id=13, params={
        "serviceId": UUID.SVC_ID,
        "characteristicId": UUID.CHAR_TX,
        "message": base64.b64encode(payload).decode("ascii"),
    })

    kinds = [k for (k, _) in dev.display_events]
    assert kinds == ["text", "matrix", "clear", "pixel"]
    assert dev.display_events[0] == ("text", "Hello")
    assert dev.display_events[3] == ("pixel", (2, 3, True))
