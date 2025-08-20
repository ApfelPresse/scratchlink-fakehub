# main.py
import asyncio
import logging
from hub import ScratchLinkHub
from microbit import MicrobitDevice
from wedo import WeDoDevice, WedoSensors

logging.basicConfig(level=logging.DEBUG, format="[%(asctime)s] [%(levelname)s] %(message)s")


class MyFakeWeDo(WeDoDevice):

    def __init__(self):
        super().__init__(device_name="Fake-Wedo", devices={
            1: WedoSensors.motor,
            2: WedoSensors.motor,
        })

    async def on_motor_power(self, port, power, direction):
        print(f"Motor {port} → {power} {'cw' if direction > 0 else 'ccw'}")


async def sensor_loop(device: MyFakeWeDo):
    await asyncio.sleep(2)  # Warte bis Scratch verbunden ist
    while True:
        device.set_distance(90)
        device.tilt_up()
        await asyncio.sleep(1)
        device.set_distance(10)
        device.tilt_up()
        await asyncio.sleep(1)

        # device.set_distance(10)
        # device.tilt_up()
        # await asyncio.sleep(5)
        # device.set_distance(20)
        # device.tilt_down()
        # await asyncio.sleep(5)
        # device.set_distance(30)
        # device.tilt_left()
        # await asyncio.sleep(5)
        # device.set_distance(40)
        # device.tilt_right()
        # await asyncio.sleep(5)


async def main():
    wedo = MyFakeWeDo()
    microbit = MicrobitDevice()
    hub = ScratchLinkHub(devices=[microbit, wedo])

    await asyncio.gather(
        hub.start(),
        #sensor_loop(wedo),
    )


if __name__ == "__main__":
    asyncio.run(main())
