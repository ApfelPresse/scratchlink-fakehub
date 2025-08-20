import asyncio
import base64
import json
import logging
from typing import Dict, Optional
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from peripheral_interface import PeripheralInterface


class UUID:
    PORT_SERVICE = "00001523-1212-efde-1523-785feabcd123"
    PORT_CHAR = "00001527-1212-efde-1523-785feabcd123"
    PORT_NOTIFY_CHAR = "00001528-1212-efde-1523-785feabcd123"
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


class DevicePeripheral(PeripheralInterface):
    def __init__(self, device_name="Fake-Wedo"):
        super().__init__(device_name)
        self.notifications_ports = False
        self.notifications_sensor = False

    async def stop(self):
        pass


class WeDoDevice(DevicePeripheral):
    def __init__(self, device_name="Fake-Wedo", devices: Optional[Dict[int, str]] = None):
        super().__init__(device_name)
        self.devices = devices or {}
        self.motor_power = {port: 100 for port, dev in self.devices.items() if dev == WedoSensors.motor}
        self.tilt_x, self.tilt_y = 0, 200
        self.ws = None
        self.push_task = None
        self.sensor_interval = 0.5
        self.distance_value = 0

    def register_ws(self, ws):
        self.ws = ws

    async def handle_rpc(self, ws, msg):
        self.register_ws(ws)
        return await super().handle_rpc(ws, msg)

    async def start_notifications(self, ws, msg_id, params):
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}))
        svc, char = params.get("serviceId"), params.get("characteristicId")
        logging.debug(f"[RECV] startNotifications → svc={svc[-4:]}, char={char[-4:]}")

        if svc == UUID.PORT_SERVICE and char == UUID.PORT_CHAR and not self.notifications_ports:
            self.notifications_ports = True
            for port, dev in self.devices.items():
                logging.info(f"[SEND attach] port={port} type={dev}")
                await ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "method": "characteristicDidChange",
                    "params": {
                        "serviceId": UUID.PORT_SERVICE,
                        "characteristicId": UUID.PORT_CHAR,
                        "encoding": "base64",
                        "message": self.encode_attach(port, dev),
                    }
                }))

        if svc == UUID.SENSOR_SERVICE and char == UUID.SENSOR_CHAR and not self.notifications_sensor:
            self.notifications_sensor = True
            if not self.push_task:
                self.push_task = asyncio.create_task(self._push_loop())

    async def stop_notifications(self, ws, msg_id, params):
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}))
        svc, char = params.get("serviceId"), params.get("characteristicId")

        if svc == UUID.SENSOR_SERVICE and char == UUID.SENSOR_CHAR:
            self.notifications_sensor = False
            if self.push_task:
                self.push_task.cancel()
                self.push_task = None

        if svc == UUID.PORT_SERVICE and char == UUID.PORT_CHAR:
            self.notifications_ports = False

    async def write(self, ws, msg_id, params):
        data = base64.b64decode(params.get("message", ""))
        if len(data) >= 3:
            port = data[0]
            pwr = int(data[-1])
            power = pwr - 256 if pwr >= 128 else pwr
            direction = 1 if power >= 0 else -1
            self.motor_power[port] = max(0, min(127, abs(power)))
            await self.on_motor_power(port, self.motor_power[port], direction)
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}))

    async def _push_loop(self):
        try:
            while self.notifications_sensor and self.ws:
                for port, device in self.devices.items():
                    if device == WedoSensors.distance:
                        await self.ws.send(self._sensor_msg(port, [0]))
                        await asyncio.sleep(0.05)
                    elif device == WedoSensors.tilt:
                        await self.ws.send(self._sensor_msg(port, [0, 0]))
                        await asyncio.sleep(0.05)

                    payload = self.encode_sensor(port, device)
                    msg = {
                        "jsonrpc": "2.0",
                        "method": "characteristicDidChange",
                        "params": {
                            "serviceId": UUID.PORT_SERVICE,
                            "characteristicId": UUID.PORT_CHAR,
                            "encoding": "base64",
                            "message": payload,
                        }
                    }
                    logging.debug(f"-> [SEND] {msg}")
                    await self.ws.send(json.dumps(msg))
                await asyncio.sleep(self.sensor_interval)
        except (ConnectionClosedError, ConnectionClosedOK):
            pass

    def _sensor_msg(self, port: int, values: list[int]) -> str:
        return json.dumps({
            "jsonrpc": "2.0",
            "method": "characteristicDidChange",
            "params": {
                "serviceId": UUID.PORT_SERVICE,
                "characteristicId": UUID.PORT_CHAR,
                "encoding": "base64",
                "message": b64(bytes([0x05, port] + values)),
            }
        })

    def encode_attach(self, port: int, device: str) -> str:
        dev_type = DEVICE_TYPES[device]
        return b64(bytes([
            port, 0x01, 0x00, dev_type,
            0x00, 0x01, 0x01, 0x10,
            0x00, 0x00, 0x00, 0x10
        ]))

    def encode_sensor(self, port: int, device: str) -> str:
        if device == WedoSensors.distance:
            return b64(bytes([0x05, port, max(0, min(self.distance_value, 255))]))
        elif device == WedoSensors.tilt:
            return b64(bytes([0x05, port, self.tilt_x, self.tilt_y]))
        elif device == WedoSensors.motor:
            val = self.motor_power.get(port, 100)
            return b64(bytes([0x05, port, val]))
        raise Exception("Unknown device type")

    def find_port(self, sensor_type: str) -> Optional[int]:
        return next((port for port, dev in self.devices.items() if dev == sensor_type), None)

    def set_distance(self, value: int):
        port = self.find_port(WedoSensors.distance)
        if port is not None:
            self.distance_value = max(0, min(255, value))
            logging.info(f"→ [DISTANCE] value={self.distance_value}")
        else:
            logging.warning("No distance sensor configured")

    async def on_motor_power(self, port: int, power: int, direction: int):
        logging.info(f"→ [MOTOR] port={port} dir={'cw' if direction > 0 else 'ccw'} power={power}")

    def set_tilt(self, x: int, y: int):
        self.tilt_x = max(0, min(255, x))
        self.tilt_y = max(0, min(255, y))

    def tilt_up(self): self.set_tilt(0, 60)
    def tilt_down(self): self.set_tilt(0, 30)
    def tilt_left(self): self.set_tilt(60, 0)
    def tilt_right(self): self.set_tilt(30, 0)

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
            (255, 255, 0), (255, 128, 0), (0, 255, 255), (255, 0, 255), (128, 128, 128)
        ]
        return table[idx % len(table)]
