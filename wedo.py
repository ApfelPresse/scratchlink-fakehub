# wedo.py
import asyncio
import base64
import json
import logging
from typing import Dict, Optional
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK


class UUID:
    PORT_SERVICE = "00001523-1212-efde-1523-785feabcd123"
    PORT_CHAR = "00001527-1212-efde-1523-785feabcd123"
    SENSOR_SERVICE = "00004f0e-1212-efde-1523-785feabcd123"
    SENSOR_CHAR = "00001560-1212-efde-1523-785feabcd123"
    CTRL_CHAR_TX = "00001565-1212-efde-1523-785feabcd123"
    LED_CHAR_TX = "00001565-1212-efde-1523-785feabcd123"


class WedoSensors:
    motor = "motor"
    tilt = "tilt"
    distance = "distance"


DEVICE_TYPES = {
    WedoSensors.motor: 0x01,
    WedoSensors.tilt: 0x22,
    WedoSensors.distance: 0x23,
}


def b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


class DevicePeripheral:
    def __init__(self, device_name="Fake-Wedo"):
        self.name = device_name
        self.notifications_ports = False
        self.notifications_sensor = False

    async def stop(self):
        pass

    async def handle_rpc(self, ws, msg):
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        async def send(obj):
            msg_out = json.dumps(obj)
            await ws.send(msg_out)

        if logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug(f"→ {json.dumps(msg)}")

        if method == "discover":
            await send({"jsonrpc": "2.0", "id": msg_id, "result": {}})
            await send({
                "jsonrpc": "2.0",
                "method": "didDiscoverPeripheral",
                "params": {"name": self.name, "peripheralId": "FAKE-WEDO-1234", "rssi": -40}
            })
            return True

        elif method == "connect":
            await send({"jsonrpc": "2.0", "id": msg_id, "result": {}})
            return True

        return False


class WeDoDevice(DevicePeripheral):
    def __init__(self, device_name="Fake-Wedo", devices: Optional[Dict[int, str]] = None):
        super().__init__(device_name)
        self.devices = devices or {}
        self.motor_power = {port: 100 for port, dev in self.devices.items() if dev == WedoSensors.motor}
        self.tilt_x, self.tilt_y = 0, 200
        self.ws = None
        self.tick = 0
        self.push_task = None
        self.sensor_interval = 0.5  # default auf 0.5s gesetzt
        self.distance_value = 0

    def register_ws(self, ws):
        self.ws = ws

    async def handle_rpc(self, ws, msg):
        self.register_ws(ws)
        if await super().handle_rpc(ws, msg):
            return

        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        async def send(obj):
            msg_out = json.dumps(obj)
            await ws.send(msg_out)

        if logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug(f"→ {json.dumps(msg)}")

        if method == "startNotifications":
            svc = params.get("serviceId")
            char = params.get("characteristicId")
            await send({"jsonrpc": "2.0", "id": msg_id, "result": {}})

            if svc == UUID.PORT_SERVICE and char == UUID.PORT_CHAR and not self.notifications_ports:
                self.notifications_ports = True
                for port, dev in self.devices.items():
                    await send({
                        "jsonrpc": "2.0",
                        "method": "characteristicDidChange",
                        "params": {
                            "serviceId": UUID.PORT_SERVICE,
                            "characteristicId": UUID.PORT_CHAR,
                            "encoding": "base64",
                            "message": self.encode_attach(port, dev),
                        }
                    })

            if svc == UUID.SENSOR_SERVICE and char == UUID.SENSOR_CHAR:
                self.notifications_sensor = True
                if not self.push_task:
                    self.push_task = asyncio.create_task(self._push_loop())

        elif method == "write":
            svc = params.get("serviceId", "")
            char = params.get("characteristicId", "")
            data = base64.b64decode(params.get("message", ""))
            if char.lower() == UUID.CTRL_CHAR_TX.lower() and len(data) >= 3:
                port = data[0]
                pwr = int(data[-1])
                power = pwr - 256 if pwr >= 128 else pwr
                direction = 1 if power >= 0 else -1
                self.motor_power[port] = max(0, min(127, abs(power)))
                await self.on_motor_power(port, self.motor_power[port], direction)

            if msg_id is not None:
                await send({"jsonrpc": "2.0", "id": msg_id, "result": {}})

        elif method == "stopNotifications":
            svc = params.get("serviceId")
            char = params.get("characteristicId")
            await send({"jsonrpc": "2.0", "id": msg_id, "result": {}})
            if svc == UUID.SENSOR_SERVICE and char == UUID.SENSOR_CHAR:
                self.notifications_sensor = False
                if self.push_task:
                    self.push_task.cancel()
                    self.push_task = None
            if svc == UUID.PORT_SERVICE and char == UUID.PORT_CHAR:
                self.notifications_ports = False

        elif msg_id is not None:
            await send({"jsonrpc": "2.0", "id": msg_id, "result": {}})

    async def _push_loop(self):
        try:
            while self.notifications_sensor and self.ws:
                self.tick += 1
                for port, device in self.devices.items():
                    payload = self.encode_sensor(port, device)
                    if payload:
                        msg = {
                            "jsonrpc": "2.0",
                            "method": "characteristicDidChange",
                            "params": {
                                "serviceId": UUID.SENSOR_SERVICE,
                                "characteristicId": UUID.SENSOR_CHAR,
                                "encoding": "base64",
                                "message": payload,
                            }
                        }
                        await self.ws.send(json.dumps(msg))
                await asyncio.sleep(self.sensor_interval)
        except (ConnectionClosedError, ConnectionClosedOK):
            pass

    def encode_attach(self, port: int, device: str) -> str:
        dev_type = DEVICE_TYPES[device]
        head = [0x01, 0x01, 0x00, dev_type] if port == 1 else [0x02, 0x01, 0x01, dev_type]
        body = [0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x10]
        return b64(bytes(head + body))

    def encode_sensor(self, port: int, device: str) -> str:
        if device == WedoSensors.tilt:
            logging.debug(f"→ sending tilt on port {port}")
            return b64(bytes([0x05, port, self.tilt_x, self.tilt_y]))
        elif device == WedoSensors.distance:
            val = self.distance_value
            logging.debug(f"→ sending distance on port {port}: {val}")
            return b64(bytes([0x05, port, val]))
        elif device == WedoSensors.motor:
            val = self.motor_power.get(port, 100)
            logging.debug(f"→ sending motor echo on port {port}: {val}")
            return b64(bytes([0x05, port, val]))
        return ""

    def find_port(self, sensor_type: str) -> Optional[int]:
        for port, dev in self.devices.items():
            if dev == sensor_type:
                return port
        return None

    def set_distance(self, value: int):
        port = self.find_port(WedoSensors.distance)
        if port is None:
            logging.warning("No distance sensor configured")
            return
        self.distance_value = max(0, min(255, value))
        logging.info(f"→ [DISTANCE] value={self.distance_value}")

    async def on_motor_power(self, port: int, power: int, direction: int):
        logging.info(f"→ [MOTOR] port={port} dir={'cw' if direction > 0 else 'ccw'} power={power}")

    def set_tilt(self, x: int, y: int):
        self.tilt_x = max(0, min(255, x))
        self.tilt_y = max(0, min(255, y))

    def tilt_up(self):
        logging.info(f"→ wedo tilt up")
        self.set_tilt(0, 60)

    def tilt_down(self):
        logging.info(f"→ wedo tilt down")
        self.set_tilt(0, 30)

    def tilt_left(self):
        logging.info(f"→ wedo tilt left")
        self.set_tilt(60, 0)

    def tilt_right(self):
        logging.info(f"→ wedo tilt right")
        self.set_tilt(30, 0)

    def set_sensor_interval(self, seconds: float):
        self.sensor_interval = max(0.05, seconds)
        logging.info(f"→ [SENSOR LOOP] interval set to {self.sensor_interval:.2f}s")

    async def set_light_color(self, color_index: int):
        rgb = self._palette(color_index)
        logging.info(f"→ [LED] index={color_index} → rgb={rgb}")

    @staticmethod
    def _palette(idx: int):
        table = [
            (0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (255, 128, 0), (0, 255, 255), (255, 0, 255), (128, 128, 128),
        ]
        return table[idx % len(table)]
