from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, runtime_checkable

ARROW_IN = "←"
ARROW_OUT = "→"


@dataclass
class LogStep:
    """
    Eine einzelne Log-Zeile.
    direction: "in"  -> Client -> Hub  (←)
               "out" -> Hub    -> Client (→)
    """
    direction: str
    raw_json: str
    obj: dict


def parse_log_file(path: Path) -> List[LogStep]:
    steps: List[LogStep] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue

        direction: Optional[str] = None
        if raw.startswith(ARROW_IN):
            direction = "in"
            json_part = raw[len(ARROW_IN):].strip()
        elif raw.startswith(ARROW_OUT):
            direction = "out"
            json_part = raw[len(ARROW_OUT):].strip()
        else:
            continue

        try:
            obj = json.loads(json_part)
        except Exception:
            continue

        steps.append(LogStep(direction=direction, raw_json=json_part, obj=obj))
    return steps


def b64(s: str) -> bytes:
    return base64.b64decode(s) if s else b""


@runtime_checkable
class ProtocolProfile(Protocol):
    name: str

    def is_led_write(self, msg: Dict[str, Any]) -> bool: ...

    def is_motor_write(self, msg: Dict[str, Any]) -> bool: ...

    def is_sensor_notify(self, msg: Dict[str, Any]) -> bool: ...


class WeDoProfile:
    name = "wedo"

    @staticmethod
    def _payload(msg: Dict[str, Any]) -> bytes:
        params = msg.get("params") or {}
        return b64(params.get("message", ""))

    def is_led_write(self, msg: Dict[str, Any]) -> bool:
        if not (isinstance(msg, dict) and msg.get("method") == "write"):
            return False
        data = self._payload(msg)
        return len(data) >= 4 and data[0] == 0x06 and data[1] == 0x04 and data[2] == 0x03

    @staticmethod
    def _is_motor_power_frame(payload: bytes) -> bool:
        """
        WeDo Motor-Write (tolerant, basierend auf beobachteten Frames):
          - payload[0] in {1,2}  -> Port
          - payload[1], payload[2] sind oft 0x00 oder 0x01
          - payload hat mind. 4 Bytes
        """
        if len(payload) < 4:
            return False
        port = payload[0]
        return port in (1, 2) and (
                (len(payload) == 4 and payload[1] in (0x00, 0x01) and payload[2] in (0x00, 0x01))
                or len(payload) > 4
        )

    def is_motor_write(self, msg: Dict[str, Any]) -> bool:
        if not (isinstance(msg, dict) and msg.get("method") == "write"):
            return False
        return self._is_motor_power_frame(self._payload(msg))

    def is_sensor_notify(self, msg: Dict[str, Any]) -> bool:
        """
        WeDo Sensor-Notification:
          - method == 'characteristicDidChange'
          - encoding == 'base64'
          - payload[0] == 0x05 (typischer WeDo-Sensorframe-Header)
        """
        if not (isinstance(msg, dict) and msg.get("method") == "characteristicDidChange"):
            return False
        p = msg.get("params") or {}
        if p.get("encoding") != "base64":
            return False
        payload = b64(p.get("message", ""))
        return len(payload) >= 1 and payload[0] == 0x05


class MicrobitProfile:
    name = "microbit"

    def is_led_write(self, msg: Dict[str, Any]) -> bool: return False

    def is_motor_write(self, msg: Dict[str, Any]) -> bool: return False

    def is_sensor_notify(self, msg: Dict[str, Any]) -> bool: return False


PROFILES: Dict[str, ProtocolProfile] = {
    "wedo": WeDoProfile(),
    "microbit": MicrobitProfile(),
}

_default_wedo = PROFILES["wedo"]


def is_led_write(msg: Dict[str, Any]) -> bool:
    return _default_wedo.is_led_write(msg)


def is_motor_write(msg: Dict[str, Any]) -> bool:
    return _default_wedo.is_motor_write(msg)


def is_sensor_notify(msg: Dict[str, Any]) -> bool:
    return _default_wedo.is_sensor_notify(msg)


class ScratchFakeRunner:
    def __init__(self, device, ws, *, profile: ProtocolProfile = _default_wedo):
        self.device = device
        self.ws = ws
        self.profile = profile  # reserviert für spätere Filterlogik

    async def play(self, steps: List[LogStep], *, only_methods: Optional[Iterable[str]] = None):
        allowed = set(only_methods) if only_methods else None
        for step in steps:
            if step.direction != "in" or step.obj is None:
                continue
            if allowed and step.obj.get("method") not in allowed:
                continue
            await self.device.handle_rpc(self.ws, step.obj)
            await asyncio.sleep(0)
