# main_demo_wedo.py
import asyncio
import logging

from scratchlink_fakehub.device import FakeDevice
from scratchlink_fakehub.hub import ScratchLinkHub
from scratchlink_fakehub.wedo import WeDoDevice, WedoSensors

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

DIST_STEP_S = 0.7
CYCLE_PAUSE_S = 1.2

async def wait_until_ready(wedo: WeDoDevice):
    while getattr(wedo, "ws", None) is None:
        await asyncio.sleep(0.1)
    for _ in range(200):
        if getattr(wedo, "notifications_ports", False) and getattr(wedo, "notifications_sensor", False):
            break
        await asyncio.sleep(0.1)

async def demo_loop(wedo: WeDoDevice):
    await wait_until_ready(wedo)
    wedo.set_sensor_interval(0.5)
    while True:
        for d in (10, 40, 80, 140, 200, 80, 40):
            wedo.set_distance(d)
            await asyncio.sleep(DIST_STEP_S)
        await asyncio.sleep(CYCLE_PAUSE_S)

async def main():
    link = FakeDevice()
    wedo = WeDoDevice(devices={
        1: WedoSensors.distance,
        2: WedoSensors.motor,
    })
    hub = ScratchLinkHub(link, devices=[wedo])
    await asyncio.gather(hub.start(), demo_loop(wedo))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Exiting…")
