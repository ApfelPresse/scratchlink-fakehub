import asyncio
import base64
import json
import logging
import os
from typing import Sequence, Dict, Any, Optional
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from .peripheral_interface import PeripheralInterface

HEARTBEAT_HZ = float(os.getenv("SL_HEARTBEAT_HZ", "1.0"))


def b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def b64_to_bytes(s: str) -> bytes:
    try:
        return base64.b64decode(s) if s else b""
    except Exception:
        return b""


class UUID:
    SVC_ID = 61445

    CHAR_RX = "5261da01-fa7e-42ab-850b-7c80220097cc"   # notify
    CHAR_TX = "5261da02-fa7e-42ab-850b-7c80220097cc"   # write

    BTN_SERVICE = "E95D9882-251D-470A-A062-FA1922DFA9A8"
    BTN_A_CHAR  = "E95DDA90-251D-470A-A062-FA1922DFA9A8"
    BTN_B_CHAR  = "E95DDA91-251D-470A-A062-FA1922DFA9A8"
    BTN_AB_CHAR = "E95DDA92-251D-470A-A062-FA1922DFA9A8"

    ACCEL_SERVICE   = "E95D0753-251D-470A-A062-FA1922DFA9A8"
    ACCEL_DATA_CHAR = "E95DCA4B-251D-470A-A062-FA1922DFA9A8"

    PIN_EVENT_OPCODE = 0xA5


class DevicePeripheral(PeripheralInterface):
    def __init__(self, device_name="Fake-Microbit"):
        super().__init__(device_name)
        self.ws = None

    def register_ws(self, ws):
        self.ws = ws

    async def stop(self):
        pass


class MicrobitDevice(DevicePeripheral):
    def __init__(self, device_name="Fake-Microbit"):
        super().__init__(device_name)
        self.notifications_rx = False
        self.push_task: Optional[asyncio.Task] = None
        self._hb_t = 0

    async def handle_rpc(self, ws, msg):
        self.register_ws(ws)
        logging.debug(f"[RPC] received: {msg}")
        return await super().handle_rpc(ws, msg)

    async def read(self, ws, msg_id, params):
        logging.debug(f"[READ] params={params}")
        if params.get("startNotifications"):
            logging.debug("[READ] startNotifications==true → delegating to start_notifications")
            await self.start_notifications(ws, msg_id, params)
        else:
            logging.debug("[READ] → simple ACK (no startNotifications)")
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}))

    async def start_notifications(self, ws, msg_id, params):
        logging.debug(f"[START_NOTIFICATIONS] called with params: {params}")
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}))

        svc, char = params.get("serviceId"), params.get("characteristicId")
        if not svc or not char:
            raise Exception("[START_NOTIFICATIONS] Missing serviceId or characteristicId!")

        logging.debug(f"[START_NOTIFICATIONS] serviceId={svc} char={char}")

        if svc == UUID.SVC_ID and (char or "").lower() == UUID.CHAR_RX.lower():
            if self.notifications_rx:
                logging.warning("[START_NOTIFICATIONS] Already running → ignored")
            else:
                logging.info("[START_NOTIFICATIONS] Starting RX notifications + push loop")
                self.notifications_rx = True
                if not self.push_task:
                    self.push_task = asyncio.create_task(self._push_loop())
        else:
            logging.debug(f"[START_NOTIFICATIONS] → conditions not met (svc={svc}, char={char})")

    async def stop_notifications(self, ws, msg_id, params):
        logging.debug(f"[STOP_NOTIFICATIONS] called with params: {params}")
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}))

        svc, char = params.get("serviceId"), params.get("characteristicId")

        if svc == UUID.SVC_ID and (char or "").lower() == UUID.CHAR_RX.lower():
            logging.info("[STOP_NOTIFICATIONS] Stopping RX notifications")
            self.notifications_rx = False
            if self.push_task:
                self.push_task.cancel()
                self.push_task = None
        else:
            logging.debug(f"[STOP_NOTIFICATIONS] → no matching service/char")

    async def _push_loop(self):
        if HEARTBEAT_HZ <= 0:
            logging.warning("[PUSH_LOOP] HEARTBEAT_HZ <= 0 → no heartbeat sent")
            return

        logging.info("[PUSH_LOOP] Starting heartbeat loop")
        try:
            period = 1.0 / HEARTBEAT_HZ
            logging.debug(f"[PUSH_LOOP] Interval = {period:.3f}s")

            while self.notifications_rx and self.ws:
                await asyncio.sleep(period)
                self._hb_t = (self._hb_t + 1) & 0xFF
                payload = self._heartbeat_payload(self._hb_t)
                logging.debug(f"[PUSH_LOOP] sending heartbeat tick={self._hb_t}")
                await self._notify(UUID.SVC_ID, UUID.CHAR_RX, payload)

            logging.info("[PUSH_LOOP] Exiting normally (no longer active)")
        except Exception as e:
            logging.exception(f"[PUSH_LOOP] Exception: {e}")
            raise

    @staticmethod
    def _heartbeat_payload(t: int) -> bytes:
        return bytes(((t + i * 11) & 0xFF for i in range(8)))

    async def _notify(self, service_id: Any, char_id: str, payload: bytes):
        if not self.ws:
            logging.warning("[_NOTIFY] No WebSocket connection available!")
            return
        msg = {
            "jsonrpc": "2.0",
            "method": "characteristicDidChange",
            "params": {
                "serviceId": service_id,
                "characteristicId": char_id,
                "encoding": "base64",
                "message": b64(payload),
            },
        }
        logging.debug(f"[SEND] notify svc={service_id} char={char_id[-4:]} len={len(payload)}")
        await self.ws.send(json.dumps(msg))

    async def write(self, ws, msg_id, params):
        payload = b64_to_bytes(params.get("message") or "")
        opcode = payload[0] if payload else None
        args = payload[1:] if len(payload) > 1 else b""

        logging.debug(f"[WRITE] opcode=0x{(opcode or 0):02X} args={args.hex()}")

        if opcode == 0x81:
            text = args.decode("utf-8", errors="replace")
            await self.on_display_text(text)

        elif opcode == 0x82:
            rows = list(args[:5]) + [0] * (5 - len(args))
            if all(b == 0 for b in rows):
                await self.on_clear_display()
            else:
                await self.on_display_matrix(rows)

        elif opcode == 0x80:
            if len(args) >= 3:
                x, y, on = int(args[0]), int(args[1]), bool(args[2])
                await self.on_set_pixel(x, y, on)
            else:
                logging.warning(f"[DISPLAY] raw {args.hex()} (short)")

        else:
            logging.warning(f"[UNKNOWN OPCODE] 0x{(opcode or 0):02X} args={args.hex()}")

        await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}))

    async def on_display_text(self, text: str):
        logging.info(f"[DISPLAY] text={text!r}")

    async def on_display_matrix(self, rows: Sequence[int]):
        grid = "\n".join(
            "".join("#" if (r >> (4 - c)) & 1 else "." for c in range(5)) for r in rows[:5]
        )
        logging.info(f"[DISPLAY] matrix:\n{grid}")

    async def on_clear_display(self):
        logging.info("[DISPLAY] clear")

    async def on_set_pixel(self, x: int, y: int, on: bool):
        logging.info(f"[DISPLAY] set_pixel x={x} y={y} on={on}")

    async def button_a(self, pressed: Optional[bool] = None, value: Optional[int] = None):
        v = value if value is not None else (1 if pressed else 0)
        await self._notify(UUID.BTN_SERVICE, UUID.BTN_A_CHAR, bytes([v]))

    async def button_b(self, pressed: Optional[bool] = None, value: Optional[int] = None):
        v = value if value is not None else (1 if pressed else 0)
        await self._notify(UUID.BTN_SERVICE, UUID.BTN_B_CHAR, bytes([v]))

    async def button_ab(self, pressed: Optional[bool] = None, value: Optional[int] = None):
        v = value if value is not None else (1 if pressed else 0)
        await self._notify(UUID.BTN_SERVICE, UUID.BTN_AB_CHAR, bytes([v]))

    async def press_a(self):    await self.button_a(True)
    async def release_a(self): await self.button_a(False)
    async def press_b(self):    await self.button_b(True)
    async def release_b(self): await self.button_b(False)

    async def pin_connected(self, pin: int, connected: bool):
        await self._notify(UUID.SVC_ID, UUID.CHAR_RX, bytes([UUID.PIN_EVENT_OPCODE, pin & 0xFF, 1 if connected else 0]))

    async def accelerometer(self, x: int, y: int, z: int):
        for v in (x, y, z):
            if not (-32768 <= v <= 32767):
                raise ValueError("accelerometer values must be int16")
        payload = (
                (x & 0xFFFF).to_bytes(2, "little")
                + (y & 0xFFFF).to_bytes(2, "little")
                + (z & 0xFFFF).to_bytes(2, "little")
        )
        await self._notify(UUID.ACCEL_SERVICE, UUID.ACCEL_DATA_CHAR, payload)

    async def tilt_front(self):  await self.accelerometer(0, +800, 1000)
    async def tilt_back(self):   await self.accelerometer(0, -800, 1000)
    async def tilt_left(self):   await self.accelerometer(-800, 0, 1000)
    async def tilt_right(self):  await self.accelerometer(+800, 0, 1000)
    async def tilt_any(self):    await self.accelerometer(+300, +300, 1000)
    async def moved(self):       await self.accelerometer(+1500, 0, 1000)
    async def shaken(self):      await self.accelerometer(+3000, +3000, 1000)
    async def jumped(self):      await self.accelerometer(0, 0, 400)
