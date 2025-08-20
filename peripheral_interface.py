import json
import logging


class PeripheralInterface:
    def __init__(self, device_name="Fake-Wedo"):
        self.name = device_name

    async def discover(self, ws, msg_id):
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}))
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "method": "didDiscoverPeripheral",
            "params": {"name": self.name, "peripheralId": "FAKE-WEDO-1234", "rssi": -40}
        }))

    async def connect(self, ws, msg_id):
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}))

    async def start_notifications(self, ws, msg_id, params):
        pass

    async def stop_notifications(self, ws, msg_id, params):
        pass

    async def write(self, ws, msg_id, params):
        pass

    async def read(self, ws, msg_id, params):
        pass

    async def handle_rpc(self, ws, msg):
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        logging.debug(f"→ {json.dumps(msg)}")

        if method == "discover":
            await self.discover(ws, msg_id)
        elif method == "connect":
            await self.connect(ws, msg_id)
        elif method == "startNotifications":
            await self.start_notifications(ws, msg_id, params)
        elif method == "stopNotifications":
            await self.stop_notifications(ws, msg_id, params)
        elif method == "write":
            await self.write(ws, msg_id, params)
        elif method == "read":
            await self.read(ws, msg_id, params)
        else:
            logging.debug(f"ACTION → fallback ACK method {method}")
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}))
