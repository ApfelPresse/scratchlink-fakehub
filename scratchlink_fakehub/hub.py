import asyncio
import json
import logging

from websockets import serve
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

logging.getLogger("websockets").addHandler(logging.NullHandler())
logging.getLogger("websockets").propagate = False


class ScratchLinkHub:
    def __init__(self, link, devices):
        self.devices = devices
        self.link = link
        self.ws = None
        self.server = None
        self.push_task = None

    async def start(self, host="127.0.0.1", port=20111):
        logging.info(f"Listening on ws://{host}:{port}/")
        self.server = await serve(self._handle_session, host, port)
        await asyncio.Future()

    def write_to_log(self, message: str):
        with open("debug_message.json", "a+") as f:
            f.write(message + "\n")

    async def send(self, message: str):
        logging.debug("→ %s", message)
        self.write_to_log(f"→ {message}")
        await self.ws.send(message)

    async def _handle_session(self, websocket):
        self.ws = websocket

        logging.info("CONNECTED")
        try:
            async for raw in websocket:
                self.write_to_log(f"← {raw}")
                logging.debug("← %s", raw)
                try:
                    msg = json.loads(raw)
                    await self.link.handle_rpc(self, msg)
                    for device in self.devices:
                        await device.handle_rpc(self, msg)
                except Exception as e:
                    logging.warning(f"RPC error: {e}")
        except (ConnectionClosedError, ConnectionClosedOK):
            logging.info("DISCONNECTED")
        finally:
            for device in self.devices:
                await device.stop()
