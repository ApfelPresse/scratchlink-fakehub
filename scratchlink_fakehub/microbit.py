import asyncio
import base64
import json
import logging
import os
from typing import Optional, Sequence, Any

from .peripheral_interface import PeripheralInterface

HEARTBEAT_HZ = float(os.getenv("SL_HEARTBEAT_HZ", "10.0"))
TILT_MAG = 800
LOG_PREFIX = "[microbit]"

def b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")

def b64_to_bytes(s: str) -> bytes:
    try:
        return base64.b64decode(s) if s else b""
    except Exception:
        return b""

class UUID:
    SVC_ID  = 0xF005  # 61445
    CHAR_RX = "5261da01-fa7e-42ab-850b-7c80220097cc"  # notify → Scratch liest hier
    CHAR_TX = "5261da02-fa7e-42ab-850b-7c80220097cc"  # write  → Scratch schreibt hier

GESTURE_NONE   = 0
GESTURE_SHAKEN = 1
GESTURE_JUMPED = 2
GESTURE_MOVED  = 4

OP_SET_PIXEL   = 0x80
OP_DISPLAY_TXT = 0x81
OP_DISPLAY_5x5 = 0x82

class MicrobitDevice(PeripheralInterface):
    def __init__(self, device_name: str = "Fake-Device"):
        super().__init__(device_name)
        self.ws = None
        self._rx_enabled = False
        self._hb_task: Optional[asyncio.Task] = None

        self.tiltX = 0
        self.tiltY = 0
        self.btnA = 0
        self.btnB = 0
        self.pin0 = 0
        self.pin1 = 0
        self.pin2 = 0
        self.gesture = GESTURE_NONE

        logging.info(f"{LOG_PREFIX} init name={self.name!r}, HEARTBEAT_HZ={HEARTBEAT_HZ}")

    async def handle_rpc(self, ws, msg):
        self.ws = ws
        return await super().handle_rpc(ws, msg)

    async def read(self, ws, msg_id, params):
        logging.debug(f"{LOG_PREFIX} READ params={params}")
        await self._ack(ws, msg_id)
        if params.get("startNotifications"):
            await self._maybe_start_notifications(ws, params)

    async def start_notifications(self, ws, msg_id, params):
        logging.debug(f"{LOG_PREFIX} startNotifications params={params}")
        await self._ack(ws, msg_id)
        await self._maybe_start_notifications(ws, params)

    async def stop_notifications(self, ws, msg_id, params):
        logging.debug(f"{LOG_PREFIX} stopNotifications params={params}")
        await self._ack(ws, msg_id)
        svc, char = params.get("serviceId"), (params.get("characteristicId") or "").lower()
        if svc == UUID.SVC_ID and char == UUID.CHAR_RX.lower():
            logging.info(f"{LOG_PREFIX} RX notifications stopping")
            self._rx_enabled = False
            if self._hb_task:
                self._hb_task.cancel()
                self._hb_task = None

    async def write(self, ws, msg_id, params):
        svc = params.get("serviceId")
        char = (params.get("characteristicId") or "").lower()
        payload = b64_to_bytes(params.get("message") or "")
        logging.debug(f"{LOG_PREFIX} WRITE svc={svc} char={char[-4:]} payload={payload.hex() if payload else '∅'}")

        if svc == UUID.SVC_ID and char == UUID.CHAR_TX.lower():
            await self._handle_display_write(payload)
        else:
            logging.debug(f"{LOG_PREFIX} WRITE ignored (not TX)")

        await self._ack(ws, msg_id)

    async def discover(self, ws, msg_id):
        logging.debug(f"{LOG_PREFIX} DISCOVER")
        await self._ack(ws, msg_id)

    async def connect(self, ws, msg_id):
        logging.debug(f"{LOG_PREFIX} CONNECT")
        await self._ack(ws, msg_id)

    async def _maybe_start_notifications(self, ws, params):
        svc = params.get("serviceId")
        char = (params.get("characteristicId") or "").lower()
        if svc == UUID.SVC_ID and char == UUID.CHAR_RX.lower():
            if not self._rx_enabled:
                logging.info(f"{LOG_PREFIX} RX notifications starting")
                self._rx_enabled = True
                await self._snapshot()
                if HEARTBEAT_HZ > 0 and not self._hb_task:
                    self._hb_task = asyncio.create_task(self._heartbeat_loop())
            else:
                logging.debug(f"{LOG_PREFIX} RX already enabled")
        else:
            logging.debug(f"{LOG_PREFIX} startNotifications ignored for svc={svc} char={char}")

    async def _heartbeat_loop(self):
        try:
            period = 1.0 / HEARTBEAT_HZ if HEARTBEAT_HZ > 0 else 0
            logging.info(f"{LOG_PREFIX} Heartbeat @ {HEARTBEAT_HZ:.2f} Hz")
            while self._rx_enabled and self.ws:
                await self._snapshot()
                await asyncio.sleep(period if period > 0 else 0.1)
            logging.info(f"{LOG_PREFIX} Heartbeat stopped")
        except asyncio.CancelledError:
            logging.debug(f"{LOG_PREFIX} Heartbeat cancelled")
        except Exception as e:
            logging.exception(f"{LOG_PREFIX} Heartbeat error: {e}")

    @staticmethod
    async def _ack(ws, msg_id, result: Optional[dict] = None):
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": (result or {})}))

    async def _notify(self, service_id: Any, char_id: str, payload: bytes):
        if not self.ws:
            logging.warning(f"{LOG_PREFIX} notify without ws")
            return
        await self.ws.send(json.dumps({
            "jsonrpc": "2.0",
            "method": "characteristicDidChange",
            "params": {
                "serviceId": service_id,
                "characteristicId": char_id,
                "encoding": "base64",
                "message": b64(payload),
            },
        }))

    def _session_payload(self) -> bytes:
        tx = self.tiltX & 0xFFFF
        ty = self.tiltY & 0xFFFF
        return bytes([
            (tx >> 8) & 0xFF, tx & 0xFF,
            (ty >> 8) & 0xFF, ty & 0xFF,
            self.btnA & 1, self.btnB & 1,
            self.pin0 & 1, self.pin1 & 1, self.pin2 & 1,
            self.gesture & 0xFF
        ])

    async def _snapshot(self):
        payload = self._session_payload()
        logging.debug(f"{LOG_PREFIX} SNAPSHOT "
                      f"tilt=({self.tiltX},{self.tiltY}) A={self.btnA} B={self.btnB} "
                      f"pins={self.pin0}{self.pin1}{self.pin2} gesture={self.gesture}")
        await self._notify(UUID.SVC_ID, UUID.CHAR_RX, payload)

    async def _handle_display_write(self, payload: bytes):
        if not payload:
            logging.debug(f"{LOG_PREFIX} DISPLAY payload empty")
            return
        op = payload[0]
        args = payload[1:] if len(payload) > 1 else b""

        if op == OP_DISPLAY_TXT:
            text = args.decode("utf-8", errors="replace")
            await self.on_display_text(text)

        elif op == OP_DISPLAY_5x5:
            rows = list(args[:5]) + [0] * (5 - len(args))
            if all(b == 0 for b in rows):
                await self.on_clear_display()
            else:
                await self.on_display_matrix(rows)

        elif op == OP_SET_PIXEL:
            if len(args) >= 3:
                x, y, on = int(args[0]), int(args[1]), bool(args[2])
                await self.on_set_pixel(x, y, on)
            else:
                logging.warning(f"{LOG_PREFIX} DISPLAY set_pixel args too short: {args.hex()}")

        else:
            logging.warning(f"{LOG_PREFIX} DISPLAY unknown opcode=0x{op:02X} args={args.hex()}")

    async def on_display_text(self, text: str):
        logging.info(f"{LOG_PREFIX} DISPLAY text={text!r}")

    async def on_display_matrix(self, rows: Sequence[int]):
        grid = "\n".join(
            "".join("#" if (r >> (4 - c)) & 1 else "." for c in range(5)) for r in rows[:5]
        )
        logging.info(f"{LOG_PREFIX} DISPLAY matrix:\n{grid}")

    async def on_clear_display(self):
        logging.info(f"{LOG_PREFIX} DISPLAY clear")

    async def on_set_pixel(self, x: int, y: int, on: bool):
        logging.info(f"{LOG_PREFIX} DISPLAY set_pixel x={x} y={y} on={on}")

    async def button_a(self, pressed: Optional[bool] = None, value: Optional[int] = None):
        v = value if value is not None else (1 if pressed else 0)
        prev = self.btnA
        self.btnA = 1 if v else 0
        logging.debug(f"{LOG_PREFIX} button_a {prev}→{self.btnA}")
        await self._snapshot()

    async def button_b(self, pressed: Optional[bool] = None, value: Optional[int] = None):
        v = value if value is not None else (1 if pressed else 0)
        prev = self.btnB
        self.btnB = 1 if v else 0
        logging.debug(f"{LOG_PREFIX} button_b {prev}→{self.btnB}")
        await self._snapshot()

    async def press_a(self):    logging.info(f"{LOG_PREFIX} press A");  await self.button_a(True)
    async def release_a(self):  logging.info(f"{LOG_PREFIX} release A");await self.button_a(False)
    async def press_b(self):    logging.info(f"{LOG_PREFIX} press B");  await self.button_b(True)
    async def release_b(self):  logging.info(f"{LOG_PREFIX} release B");await self.button_b(False)

    async def pin_connected(self, pin: int, connected: bool):
        if pin not in (0, 1, 2):
            logging.warning(f"{LOG_PREFIX} pin_connected invalid pin={pin}")
            return
        val = 1 if connected else 0
        if pin == 0: self.pin0 = val
        if pin == 1: self.pin1 = val
        if pin == 2: self.pin2 = val
        logging.info(f"{LOG_PREFIX} pin{pin} connected={connected}")
        await self._snapshot()

    async def _tilt(self, x: int, y: int):
        self.tiltX, self.tiltY = int(x), int(y)
        logging.info(f"{LOG_PREFIX} tilt set X={self.tiltX} Y={self.tiltY}")
        await self._snapshot()

    async def tilt_front(self):
        logging.debug(f"{LOG_PREFIX} tilt_front")
        await self._tilt(0, +TILT_MAG)

    async def tilt_back(self):
        logging.debug(f"{LOG_PREFIX} tilt_back")
        await self._tilt(0, -TILT_MAG)

    async def tilt_left(self):
        logging.debug(f"{LOG_PREFIX} tilt_left")
        await self._tilt(-TILT_MAG, 0)

    async def tilt_right(self):
        logging.debug(f"{LOG_PREFIX} tilt_right")
        await self._tilt(+TILT_MAG, 0)

    async def tilt_any(self):
        logging.debug(f"{LOG_PREFIX} tilt_any")
        await self._tilt(+300, +300)

    async def _gesture(self, g: int, label: str):
        prev = self.gesture
        self.gesture = g
        logging.info(f"{LOG_PREFIX} gesture {label} ({prev}→{self.gesture})")
        await self._snapshot()

    async def moved(self):
        await self._gesture(GESTURE_MOVED, "moved")

    async def shaken(self):
        await self._gesture(GESTURE_SHAKEN, "shaken")

    async def jumped(self):
        await self._gesture(GESTURE_JUMPED, "jumped")

    async def reset_tilt(self):
        self.tiltX = self.tiltY = 0
        logging.debug(f"{LOG_PREFIX} reset_tilt")
        await self._snapshot()