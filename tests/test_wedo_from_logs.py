import json
import logging
from pathlib import Path

import pytest

from conftest import FakeWebSocket
from scratchlink_fakehub.wedo import WeDoDevice, WedoSensors, UUID
from tests.scratch_fake import parse_log_file, ScratchFakeRunner

LED_LOG = "debug_message_wedo_led.json"
DIST_TILT_LOG = "debug_message_wedo_distance_tilt.json"
MOTOR_LOG = "debug_message_wedo_motor_motor.json"


def _load_steps(name: str):
    base = Path(__file__).resolve().parent / "data"
    path = base / name
    assert path.exists(), f"Log file not found: {path}"
    return parse_log_file(path)


@pytest.mark.asyncio
async def test_led_from_log():
    steps = _load_steps(LED_LOG)

    wedo = WeDoDevice()
    ws = FakeWebSocket(incoming=[])

    calls = []

    def _set_light_color(r: int, g: int, b: int):
        calls.append((r, g, b))

    wedo.set_light_color = _set_light_color
    logging.info(calls)

    await ScratchFakeRunner(wedo, ws).play(steps)

    assert len(calls) > 0
    assert calls[0] == (0, 0, 255), f"Expected first LED call to be (0,0,255), got {calls[0]!r}"
    assert calls[1] == (0, 255, 255), f"Expected first LED call to be (0,255,255), got {calls[0]!r}"

    acks = [json.loads(m) for m in ws.sent if '"result": {}' in m]
    assert acks, "Expected ACKs from device for registration sequence"


@pytest.mark.asyncio
async def test_distance_tilt_from_log(tmp_path):
    steps = _load_steps(DIST_TILT_LOG)

    d = WeDoDevice(devices={1: WedoSensors.tilt, 2: WedoSensors.distance})
    ws = FakeWebSocket(incoming=[])

    calls = []
    _orig_encode = d.encode_attach

    def _spy_encode_attach(port, device):
        calls.append((port, device))
        return _orig_encode(port, device)

    d.encode_attach = _spy_encode_attach

    await ScratchFakeRunner(d, ws).play(steps)

    assert len(calls) >= 2, f"Expected at least 2 attach calls, got {calls!r}"
    assert calls[0] == (1, WedoSensors.tilt), f"First attach should be tilt on port 1, got {calls[0]!r}"
    assert calls[1] == (2, WedoSensors.distance), f"Second attach should be distance on port 2, got {calls[1]!r}"

    acks = [json.loads(m) for m in ws.sent if '"result": {}' in m]
    assert acks, "Expected ACKs from device for mode writes / startNotifications"


@pytest.mark.asyncio
async def test_sensor_registration_from_log():
    steps = _load_steps(DIST_TILT_LOG)

    d = WeDoDevice(devices={1: WedoSensors.tilt, 2: WedoSensors.distance, 9: WedoSensors.motor})
    ws = FakeWebSocket(incoming=[])

    calls = []
    _orig_encode = d.encode_attach

    def _spy_encode_attach(port, device):
        calls.append((port, device))
        return _orig_encode(port, device)

    d.encode_attach = _spy_encode_attach

    await ScratchFakeRunner(d, ws).play(steps)

    assert d.notifications_ports, "Ports notifications not enabled — registration did not start"

    expected = [(1, WedoSensors.tilt), (2, WedoSensors.distance), (9, WedoSensors.motor)]
    assert len(calls) >= len(expected), f"Expected at least {len(expected)} attach calls, got {calls!r}"
    assert calls[:len(expected)] == expected, f"Attach order/content mismatch: expected={expected}, got={calls}"

    acks = [json.loads(m) for m in ws.sent if '"result": {}' in m]
    assert acks, "Expected ACKs from device for registration sequence"


@pytest.mark.asyncio
async def test_start_notifications_sensor_from_log():
    steps = _load_steps(DIST_TILT_LOG)

    d = WeDoDevice(devices={1: WedoSensors.tilt, 2: WedoSensors.distance})
    ws = FakeWebSocket(incoming=[])

    sensor_ids = [
        s.obj["id"] for s in steps
        if s.direction == "in" and s.obj and s.obj.get("method") == "startNotifications"
           and s.obj.get("params", {}).get("serviceId") == UUID.SENSOR_SERVICE
           and s.obj.get("params", {}).get("characteristicId") == UUID.SENSOR_CHAR
    ]
    if not sensor_ids:
        pytest.skip("Log has no startNotifications for SENSOR_SERVICE")

    await ScratchFakeRunner(d, ws).play(steps)

    assert d.notifications_sensor is True, "Sensor notifications not enabled"
    assert d.push_task is not None, "Sensor push task not started"

    sent = [json.loads(m) for m in ws.sent]
    assert any(m.get("id") == sensor_ids[0] and "result" in m for m in sent), \
        "ACK for startNotifications(SENSOR) missing"


@pytest.mark.asyncio
async def test_motor_motor_from_log(tmp_path):
    steps = _load_steps(MOTOR_LOG)

    d = WeDoDevice()
    ws = FakeWebSocket(incoming=[])

    calls = []

    async def _on_motor_power(port: int, power: int, direction: int):
        calls.append((port, power, direction))

    d.on_motor_power = _on_motor_power

    await ScratchFakeRunner(d, ws).play(steps)

    assert len(calls) >= 2, f"Expected at least two motor power calls, got {calls!r}"

    for port, power, direction in calls:
        assert port in (1, 2), f"Unexpected motor port {port}"
        assert 0 <= power <= 127, f"Power out of range: {power}"
        assert direction in (-1, 1), f"Direction must be -1 or 1: {direction}"

    last_power_by_port = {}
    for port, power, direction in calls:
        last_power_by_port[port] = power

    for port, expected_power in last_power_by_port.items():
        assert d.motor_power[port] == expected_power, (
            f"Final motor_power mismatch on port {port}: "
            f"expected {expected_power}, got {d.motor_power[port]}"
        )

    assert len({p for p, _, _ in calls}) >= 2, "Expected writes to at least two motor ports"

    acks = [json.loads(m) for m in ws.sent if '"result": {}' in m]
    assert acks, "Expected ACKs from device for motor writes"


@pytest.mark.asyncio
async def test_start_notifications_ports_from_log():
    steps = _load_steps(MOTOR_LOG)

    d = WeDoDevice(devices={1: WedoSensors.tilt, 2: WedoSensors.distance, 9: WedoSensors.motor})
    ws = FakeWebSocket(incoming=[])

    start_ids = [
        s.obj["id"] for s in steps
        if s.direction == "in" and s.obj and s.obj.get("method") == "startNotifications"
           and s.obj.get("params", {}).get("serviceId") == UUID.PORT_SERVICE
           and s.obj.get("params", {}).get("characteristicId") == UUID.PORT_CHAR
    ]
    if not start_ids:
        pytest.skip("Log has no startNotifications for PORT_SERVICE")

    calls = []
    _orig_encode = d.encode_attach

    def _spy_encode_attach(port, device):
        calls.append((port, device))
        return _orig_encode(port, device)

    d.encode_attach = _spy_encode_attach

    await ScratchFakeRunner(d, ws).play(steps)

    assert d.notifications_ports is True, "Ports notifications not enabled"

    expected = set(d.devices.items())
    assert expected.issubset(set(calls)), f"Missing attach calls. expected ⊆ calls; {expected=} {calls=}"

    sent = [json.loads(m) for m in ws.sent]
    assert any(m.get("id") == start_ids[0] and "result" in m for m in sent), \
        "ACK for startNotifications(PORT) missing"

    attaches = [
        m for m in sent
        if m.get("method") == "characteristicDidChange"
           and m.get("params", {}).get("serviceId") == UUID.PORT_SERVICE
           and m.get("params", {}).get("characteristicId") == UUID.PORT_CHAR
    ]
    assert attaches, "No attach notifications emitted"
