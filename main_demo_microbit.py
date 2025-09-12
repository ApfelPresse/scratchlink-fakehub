import asyncio
import logging

from scratchlink_fakehub.device import FakeDevice
from scratchlink_fakehub.hub import ScratchLinkHub
from scratchlink_fakehub.microbit import MicrobitDevice

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

sleep = 1.0


async def wait_until_ready(device: MicrobitDevice):
    logging.info("[debug] warte auf Verbindung zu Scratch …")
    while not getattr(device, "ws", None):
        await asyncio.sleep(0.1)

    for _ in range(200):
        if getattr(device, "_rx_enabled", False):
            break
        await asyncio.sleep(0.1)

    logging.info("[debug] Verbindung steht, starte Trigger-Loop")


async def sensor_loop(device: MicrobitDevice):
    await wait_until_ready(device)

    while True:
        logging.info("[demo] PRESS A")
        await device.press_a()
        await asyncio.sleep(sleep)
        await device.release_a()

        logging.info("[demo] PRESS B")
        await device.press_b()
        await asyncio.sleep(sleep)
        await device.release_b()

        logging.info("[demo] GESTURE jumped")
        await device.jumped()
        await asyncio.sleep(sleep)
        logging.info("[demo] GESTURE clear")

        logging.info("[demo] GESTURE shaken")
        await device.shaken()
        await asyncio.sleep(sleep)
        logging.info("[demo] GESTURE clear")

        logging.info("[demo] GESTURE moved")
        await device.moved()
        await asyncio.sleep(sleep)
        logging.info("[demo] GESTURE clear")

        logging.info("[demo] TILT front (+Y)")
        await device.tilt_front()
        await asyncio.sleep(sleep)

        logging.info("[demo] TILT back (-Y)")
        await device.tilt_back()
        await asyncio.sleep(sleep)

        logging.info("[demo] TILT left (-X)")
        await device.tilt_left()
        await asyncio.sleep(sleep)

        logging.info("[demo] TILT right (+X)")
        await device.tilt_right()
        await asyncio.sleep(sleep)

        for pin in (0, 1, 2):
            logging.info(f"[demo] PIN {pin} connected = True")
            await device.pin_connected(pin, True)
            await asyncio.sleep(sleep)
            await device.pin_connected(pin, False)

        await asyncio.sleep(sleep)


async def main():
    link = FakeDevice()
    microbit = MicrobitDevice()
    hub = ScratchLinkHub(link, devices=[microbit])
    await asyncio.gather(
        hub.start(),
        sensor_loop(microbit)
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Beende…")
