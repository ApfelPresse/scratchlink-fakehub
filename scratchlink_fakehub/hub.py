import asyncio
import json
import logging
from websockets import serve
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK


class ScratchLinkHub:
    def __init__(self, devices):
        self.devices = devices
        self.ws = None
        self.server = None
        self.push_task = None

    async def start(self, host="127.0.0.1", port=20111):
        logging.info(f"Listening on ws://{host}:{port}/")
        self.server = await serve(self._handle_session, host, port)
        await asyncio.Future()

    async def _handle_session(self, websocket):
        self.ws = websocket
        logging.info("CONNECTED")
        try:
            async for raw in websocket:
                logging.debug("← %s", raw)
                try:
                    msg = json.loads(raw)
                    for device in self.devices:
                        await device.handle_rpc(websocket, msg)
                except Exception as e:
                    logging.warning(f"RPC error: {e}")
        except (ConnectionClosedError, ConnectionClosedOK):
            logging.info("DISCONNECTED")
        finally:
            for device in self.devices:
                await device.stop()
