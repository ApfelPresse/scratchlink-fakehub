# main.py
import asyncio
import logging
from hub import ScratchLinkHub
from wedo import WeDoDevice, WedoSensors

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")


class MyFakeWeDo(WeDoDevice):
    def __init__(self):
        super().__init__(device_name="Fake-Wedo", devices={
            1: WedoSensors.motor,
            2: WedoSensors.distance,
        })

    async def on_motor_power(self, port, power, direction):
        print(f"Motor {port} → {power} {'cw' if direction > 0 else 'ccw'}")



async def main():
    device = MyFakeWeDo()
    hub = ScratchLinkHub(device)
    await hub.start()

if __name__ == "__main__":
    asyncio.run(main())
