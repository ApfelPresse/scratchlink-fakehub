# hub.py
import asyncio
import json
import logging
import base64
from websockets import serve
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK


class ScratchLinkHub:
    def __init__(self, device):
        self.device = device
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
                    await self.device.handle_rpc(websocket, msg)
                except Exception as e:
                    logging.warning(f"RPC error: {e}")
        except (ConnectionClosedError, ConnectionClosedOK):
            logging.info("DISCONNECTED")
        finally:
            await self.device.stop()
