import asyncio
import base64
import json

import pytest
from websockets.exceptions import ConnectionClosedOK

from tests.conftest import FakeWebSocket, b64_to_bytes, all_json
from wedo import WeDoDevice, WedoSensors, UUID, DEVICE_TYPES


def _last_change_for(ws, char_id):
    msgs = [json.loads(m) for m in ws.sent if '"characteristicDidChange"' in m]
    for m in reversed(msgs):
        if m["params"]["characteristicId"] == char_id:
            return m
    return None


def decode_last_base64_message(ws):
    msgs = [json.loads(m) for m in ws.sent if '"message"' in m]
    assert msgs, "no base64 messages sent"
    last = msgs[-1]
    payload = b64_to_bytes(last["params"]["message"])
    return last, payload


@pytest.mark.asyncio
async def test_encode_attach_and_find_port_and_sensor_encoding():
    d = WeDoDevice(devices={1: WedoSensors.motor, 2: WedoSensors.tilt, 3: WedoSensors.distance})
    # attach encodes device type byte correctly
    enc = d.encode_attach(2, WedoSensors.tilt)
    payload = b64_to_bytes(enc)
    assert payload[0] == 2
    assert payload[3] == DEVICE_TYPES[WedoSensors.tilt]

    d.set_tilt(12, 34)
    d.set_distance(250)
    m_enc = d.encode_sensor(1, WedoSensors.motor)
    t_enc = d.encode_sensor(2, WedoSensors.tilt)
    dist_enc = d.encode_sensor(3, WedoSensors.distance)
    assert list(b64_to_bytes(m_enc)) == [0x05, 1, d.motor_power.get(1, 100)]
    assert list(b64_to_bytes(t_enc)) == [0x05, 2, 12, 34]
    assert list(b64_to_bytes(dist_enc)) == [0x05, 3, 250]

    with pytest.raises(Exception):
        d.encode_sensor(4, "mystery")


@pytest.mark.asyncio
async def test_start_notifications_attach_once_and_sensor_loop_runs_and_stops():
    d = WeDoDevice(devices={1: WedoSensors.motor, 2: WedoSensors.distance})
    ws = FakeWebSocket()
    # First start → sends ack + 2 attach frames
    await d.start_notifications(ws, 1, {"serviceId": UUID.PORT_SERVICE, "characteristicId": UUID.PORT_CHAR})
    msgs = all_json(ws.sent)
    assert msgs[0]["id"] == 1  # ACK
    attach = [m for m in msgs[1:] if m.get("method") == "characteristicDidChange"]
    assert len(attach) == 2

    # Second start on PORT should not duplicate attach when already active
    await d.start_notifications(ws, 2, {"serviceId": UUID.PORT_SERVICE, "characteristicId": UUID.PORT_CHAR})
    msgs2 = all_json(ws.sent)
    # only the ACK was added (no new characteristicDidChange right after)
    assert any(m.get("id") == 2 for m in msgs2)
    just_after = msgs2[len(msgs):]
    assert all(m.get("method") != "characteristicDidChange" for m in just_after)

    # Start sensor notifications → loop begins
    d.set_sensor_interval(0.05)
    await d.start_notifications(ws, 3, {"serviceId": UUID.SENSOR_SERVICE, "characteristicId": UUID.SENSOR_CHAR})
    await asyncio.sleep(0.12)  # allow loop to tick at least once

    # There should be at least one sensor characteristicDidChange
    assert _last_change_for(ws, UUID.PORT_CHAR) is not None

    # Stop sensor notifications → loop cancels and clears task
    await d.stop_notifications(ws, 4, {"serviceId": UUID.SENSOR_SERVICE, "characteristicId": UUID.SENSOR_CHAR})
    assert d.push_task is None
    assert d.notifications_sensor is False

    # Stop port notifications
    await d.stop_notifications(ws, 5, {"serviceId": UUID.PORT_SERVICE, "characteristicId": UUID.PORT_CHAR})
    assert d.notifications_ports is False


@pytest.mark.asyncio
async def test_push_loop_survives_connection_closed(monkeypatch):
    # Create a device with a distance sensor to exercise both _sensor_msg paths & encode_sensor
    d = WeDoDevice(devices={3: WedoSensors.distance})

    class BoomWS:
        def __init__(self):
            self.sent = []
            self._n = 0

        async def send(self, payload: str):
            # Fail after first send to trigger exception path in _push_loop
            self._n += 1
            if self._n > 1:
                raise ConnectionClosedOK(1000, "bye")
            self.sent.append(payload)

    boom = BoomWS()
    d.register_ws(boom)
    d.notifications_sensor = True
    # run a short-lived loop
    task = asyncio.create_task(d._push_loop())
    await asyncio.sleep(0.05)
    # after error it should exit silently without raising
    d.notifications_sensor = False
    await asyncio.sleep(0.05)
    task.cancel()
    # at least one message got sent before the exception
    assert boom.sent, "loop didn't send any message before closing"


@pytest.mark.asyncio
async def test_sensor_helpers_and_clamping_and_palette(monkeypatch):
    d = WeDoDevice(devices={1: WedoSensors.tilt, 2: WedoSensors.distance, 9: WedoSensors.motor})
    # tilt helpers
    d.tilt_up()
    assert (d.tilt_x, d.tilt_y) == (0, 60)
    d.tilt_down()
    assert (d.tilt_x, d.tilt_y) == (0, 30)
    d.tilt_left()
    assert (d.tilt_x, d.tilt_y) == (60, 0)
    d.tilt_right()
    assert (d.tilt_x, d.tilt_y) == (30, 0)
    # clamping
    d.set_tilt(-10, 400)
    assert (d.tilt_x, d.tilt_y) == (0, 255)

    # distance set with sensor present
    d.set_distance(999)
    assert d.distance_value == 255
    d.set_distance(-3)
    assert d.distance_value == 0

    # palette wraparound via set_light_color (no exception means ok)
    # also ensures _palette(idx % len)
    await d.set_light_color(25)  # 25 % 10 = 5


@pytest.mark.asyncio
async def test_find_port_and_register_ws_and_handle_rpc_delegation():
    d = WeDoDevice(devices={7: WedoSensors.motor})
    ws = FakeWebSocket()
    # register_ws via handle_rpc
    await d.handle_rpc(ws, {"method": "discover", "id": 1})
    assert d.ws is ws
    # find_port works
    assert d.find_port(WedoSensors.motor) == 7


# ---------- Basic encoding / lookup ----------

@pytest.mark.asyncio
async def test_encode_attach_and_find_port():
    d = WeDoDevice(devices={1: WedoSensors.motor, 2: WedoSensors.tilt})
    # encode_attach should include the device type code
    enc_m = d.encode_attach(1, WedoSensors.motor)
    enc_t = d.encode_attach(2, WedoSensors.tilt)
    p_m = b64_to_bytes(enc_m)
    p_t = b64_to_bytes(enc_t)
    assert p_m[0] == 1 and p_t[0] == 2
    assert p_m[3] == DEVICE_TYPES[WedoSensors.motor]
    assert p_t[3] == DEVICE_TYPES[WedoSensors.tilt]
    # find_port finds the first matching device
    assert d.find_port(WedoSensors.tilt) == 2
    assert d.find_port("missing") is None


# ---------- Sensor encoding ----------

@pytest.mark.asyncio
async def test_encode_sensor_all_types_and_errors():
    d = WeDoDevice(devices={1: WedoSensors.motor, 2: WedoSensors.tilt, 3: WedoSensors.distance})
    # default motor power 100 per __init__
    payload_motor = b64_to_bytes(d.encode_sensor(1, WedoSensors.motor))
    assert payload_motor[:3] == bytes([0x05, 1, 100])
    # tilt defaults
    payload_tilt = b64_to_bytes(d.encode_sensor(2, WedoSensors.tilt))
    assert payload_tilt[:4] == bytes([0x05, 2, d.tilt_x, d.tilt_y])
    # distance includes clamped value
    d.distance_value = 999
    payload_distance = b64_to_bytes(d.encode_sensor(3, WedoSensors.distance))
    assert payload_distance[:3] == bytes([0x05, 3, 255])
    # unknown device raises
    with pytest.raises(Exception):
        d.encode_sensor(9, "foo")


# ---------- Start/stop notifications and push loop ----------

@pytest.mark.asyncio
async def test_start_notifications_attach_once_and_push_loop_control():
    d = WeDoDevice(devices={1: WedoSensors.motor, 2: WedoSensors.tilt, 3: WedoSensors.distance})
    ws = FakeWebSocket()
    # First start: should send ACK + 3 attach messages
    await d.start_notifications(ws, 1, {"serviceId": UUID.PORT_SERVICE, "characteristicId": UUID.PORT_CHAR})
    msgs = all_json(ws.sent)
    assert msgs[0]["id"] == 1
    attach = [m for m in msgs[1:] if m.get("method") == "characteristicDidChange"]
    assert len(attach) == 3
    # Second start on the same (already active) should NOT duplicate attachments
    await d.start_notifications(ws, 2, {"serviceId": UUID.PORT_SERVICE, "characteristicId": UUID.PORT_CHAR})
    msgs2 = all_json(ws.sent)
    # Only an ACK should be added
    assert sum(1 for m in msgs2 if m.get("id") == 2) == 1

    # Start sensor push loop
    d.set_sensor_interval(0.05)
    await d.start_notifications(ws, 3, {"serviceId": UUID.SENSOR_SERVICE, "characteristicId": UUID.SENSOR_CHAR})
    await asyncio.sleep(0.12)  # allow a couple of frames
    # Stop notifications for sensors: task should be cancelled and flag reset
    await d.stop_notifications(ws, 4, {"serviceId": UUID.SENSOR_SERVICE, "characteristicId": UUID.SENSOR_CHAR})
    assert d.notifications_sensor is False
    assert d.push_task is None
    # Stop notifications for ports
    await d.stop_notifications(ws, 5, {"serviceId": UUID.PORT_SERVICE, "characteristicId": UUID.PORT_CHAR})
    assert d.notifications_ports is False


@pytest.mark.asyncio
async def test_sensor_msg_structure_and_values():
    d = WeDoDevice(devices={3: WedoSensors.distance})
    # method should be characteristicDidChange and wrap base64 message with given values
    raw = d._sensor_msg(3, [1, 2, 3])
    msg = json.loads(raw)
    assert msg["method"] == "characteristicDidChange"
    assert msg["params"]["serviceId"] == UUID.PORT_SERVICE
    payload = b64_to_bytes(msg["params"]["message"])
    assert payload == bytes([0x05, 3, 1, 2, 3])


@pytest.mark.asyncio
async def test_write_updates_motor_and_calls_hook(monkeypatch):
    d = WeDoDevice(devices={1: WedoSensors.motor})
    ws = FakeWebSocket()

    called = {}

    async def spy(port, power, direction):
        called["args"] = (port, power, direction)

    monkeypatch.setattr(d, "on_motor_power", spy)

    # Negative power via two's complement -> direction -1
    payload = bytes([1, 0x00, 0x00, 0xFF])  # -1 → abs=1
    msg = {"message": base64.b64encode(payload).decode("ascii")}
    await d.write(ws, 123, msg)
    assert called["args"] == (1, 1, -1)
    ack = json.loads(ws.sent[-1])
    assert ack["id"] == 123


@pytest.mark.asyncio
async def test_write_positive_power_and_clamp_and_unknown_port(monkeypatch):
    d = WeDoDevice(devices={})
    ws = FakeWebSocket()
    seen = {}

    async def spy(port, power, direction):
        seen["args"] = (port, power, direction)

    monkeypatch.setattr(d, "on_motor_power", spy)

    # Byte 0x7F = +127 (max), should clamp to 127, direction +1
    payload = bytes([9, 0x00, 0x00, 0x7F])
    await d.write(ws, 5, {"message": base64.b64encode(payload).decode()})
    assert seen["args"] == (9, 127, 1)
    # Port 9 should be added to motor_power dict as a side-effect
    assert d.motor_power[9] == 127


@pytest.mark.asyncio
async def test_write_ignores_short_payload():
    d = WeDoDevice(devices={1: WedoSensors.motor})
    ws = FakeWebSocket()
    # len(data) < 3 → should only ACK without touching motor_power
    await d.write(ws, 7, {"message": base64.b64encode(b'\x01\x02').decode()})
    assert d.motor_power[1] == 100  # unchanged default
    ack = json.loads(ws.sent[-1])
    assert ack["id"] == 7


@pytest.mark.asyncio
async def test_tilt_helpers_and_clamping():
    d = WeDoDevice(devices={2: WedoSensors.tilt})
    # generic set_tilt clamps
    d.set_tilt(-10, 999)
    assert d.tilt_x == 0 and d.tilt_y == 255
    d.tilt_up()
    assert (d.tilt_x, d.tilt_y) == (0, 60)
    d.tilt_down()
    assert (d.tilt_x, d.tilt_y) == (0, 30)
    d.tilt_left()
    assert (d.tilt_x, d.tilt_y) == (60, 0)
    d.tilt_right()
    assert (d.tilt_x, d.tilt_y) == (30, 0)


@pytest.mark.asyncio
async def test_set_distance_with_and_without_sensor(caplog):
    d = WeDoDevice(devices={3: WedoSensors.distance})
    d.set_distance(300)  # clamp to 255
    assert d.distance_value == 255
    d.set_distance(-5)  # clamp to 0
    assert d.distance_value == 0

    # No distance sensor configured: should warn and not change value
    d2 = WeDoDevice(devices={})
    d2.distance_value = 42
    d2.set_distance(99)
    assert d2.distance_value == 42
