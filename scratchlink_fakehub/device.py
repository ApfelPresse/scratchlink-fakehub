import json

from scratchlink_fakehub.peripheral_interface import PeripheralInterface


class FakeDevice(PeripheralInterface):

    def __init__(self, device_name="Fake-Device"):
        super().__init__()
        self.name = device_name
        self.peripheralId = device_name

    async def discover(self, ws, msg_id):
        await self.ack(ws, msg_id)
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "method": "didDiscoverPeripheral",
            "params": {"name": self.name, "peripheralId": self.peripheralId, "rssi": -40}
        }))

    async def connect(self, ws, msg_id):
        await self.ack(ws, msg_id)
