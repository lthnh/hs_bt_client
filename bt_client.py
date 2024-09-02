import asyncio
import logging
import signal

from bleak import BleakScanner, BleakClient, BleakGATTCharacteristic

NAME = "ESP_SPP_SERVER"
CHARACTERISTIC_UUID = "cdd4c6c4-7a3c-599b-324e-f93750d2f002"
VREF = 5.0

logger = logging.getLogger(__name__)

def notification_callback(char: BleakGATTCharacteristic, data: bytearray):
    val = int.from_bytes(bytes=data, byteorder='little', signed=False)
    print(f"{data} {val} {(val / 4096.0 * VREF):.3f}");

async def main():
    server = None
    devices = await BleakScanner.discover()
    logger.info("list of available devices:")
    for device in devices:
        logger.info("[Device] %s", device)
        if device.name == NAME:
            server = device

    if server:
        logger.info("found %s", server.name)
    else:
        logger.error("not found %s", NAME)
        return
    async with BleakClient(address_or_ble_device=server, winrt=dict(use_cached_services=False)) as client:
        logger.info("connected to %s", server.name)
        logger.info("begin to extract all of its services")
        for service in client.services:
            logger.info("[Service] %s", service)

            for char in service.characteristics:
                if "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char.uuid)
                        extra = f", Value: {value}"
                    except Exception as e:
                        extra = f", Error: {e}"
                else:
                    extra = ""

                if "write-without-response" in char.properties:
                    extra += f", Max write w/o rsp size: {char.max_write_without_response_size}"

                logger.info(
                    "  [Characteristic] %s (%s)%s",
                    char,
                    ",".join(char.properties),
                    extra,
                )

                if CHARACTERISTIC_UUID == char.uuid:
                    hs_char = char

                for descriptor in char.descriptors:
                    try:
                        value = await client.read_gatt_descriptor(descriptor.handle)
                        logger.info("    [Descriptor] %s, Value: %r", descriptor, value)
                    except Exception as e:
                        logger.error("    [Descriptor] %s, Error: %s", descriptor, e)

        await client.start_notify(hs_char, notification_callback)
        while True:
            if not client.is_connected:
                break
            await asyncio.sleep(1)

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
    )
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    asyncio.run(main())
