# main.py
import asyncio
import logging
from hub import ScratchLinkHub
from wedo import WeDoDevice, WedoSensors

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")


class MyFakeWeDo(WeDoDevice):
    def __init__(self):
        super().__init__(device_name="Fake-Wedo", devices={
            1: WedoSensors.distance,
            2: WedoSensors.tilt,
        })

    async def on_motor_power(self, port, power, direction):
        print(f"Motor {port} → {power} {'cw' if direction > 0 else 'ccw'}")


async def sensor_loop(device: MyFakeWeDo):
    await asyncio.sleep(2)  # Warte bis Scratch verbunden ist
    while True:
        device.set_distance(5)
        device.tilt_up()
        await asyncio.sleep(5)
        device.set_distance(20)
        device.tilt_down()
        await asyncio.sleep(5)
        device.set_distance(40)
        device.tilt_left()
        await asyncio.sleep(5)
        device.tilt_right()
        await asyncio.sleep(5)


async def main():
    device = MyFakeWeDo()
    hub = ScratchLinkHub(device)

    await asyncio.gather(
        hub.start(),
        sensor_loop(device),
    )


if __name__ == "__main__":
    asyncio.run(main())
