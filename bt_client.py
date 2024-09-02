import asyncio
from datetime import datetime
import time
import csv
import logging
import signal
from contextlib import suppress
from enum import Enum

from bleak import BleakScanner, BleakClient, BleakGATTCharacteristic

NAME = "ESP_SPP_SERVER"
HS_CHAR_UUID = "cdd4c6c4-7a3c-599b-324e-f93750d2f002"
BP_CHAR_UUID = "cdd4c6c4-7a3c-599b-324e-f93750d2f003"
VREF = 5.0

class BIOSIG(Enum):
    HS = 0
    BP = 1

logger = logging.getLogger(__name__)

file_date = f'{datetime.now().strftime('%d_%m_%Y_%H_%M')}'
hs_file = open(f'{file_date}_{BIOSIG.HS.name}.csv', 'w', newline='')
bp_file = open(f'{file_date}_{BIOSIG.BP.name}.csv', 'w', newline='')
hs_log_writer = csv.writer(hs_file, dialect='excel')
bp_log_writer = csv.writer(bp_file, dialect='excel')

start_time = None
hs_char: BleakGATTCharacteristic = None
bp_char: BleakGATTCharacteristic = None

async def notification_callback(char: BleakGATTCharacteristic, data: bytearray):
    val = int.from_bytes(bytes=data, byteorder='little', signed=False)
    sig_type = BIOSIG.HS if char == hs_char else BIOSIG.BP
    print(f"{sig_type.name} {data} {val} {(val / 4096.0 * VREF):.3f}");
    if char == hs_char:
        hs_log_writer.writerow([time.perf_counter() - start_time, val])
    if char == bp_char:
        hs_log_writer.writerow([time.perf_counter() - start_time, val])

async def main():
    global start_time, hs_char, bp_char
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

                if char.uuid == HS_CHAR_UUID:
                    hs_char = char
                if char.uuid == BP_CHAR_UUID:
                    bp_char = char

                for descriptor in char.descriptors:
                    try:
                        value = await client.read_gatt_descriptor(descriptor.handle)
                        logger.info("    [Descriptor] %s, Value: %r", descriptor, value)
                    except Exception as e:
                        logger.error("    [Descriptor] %s, Error: %s", descriptor, e)
        start_time = time.perf_counter()
        await client.start_notify(hs_char, notification_callback)
        await client.start_notify(bp_char, notification_callback)
        while True:
            if not client.is_connected:
                break
            await asyncio.sleep(1)

def signal_handler(signum, frame):
    hs_file.close()
    bp_file.close()
    # cancel all running tasks
    async def cancel_all_tasks():
        # get all tasks
        all_tasks = asyncio.all_tasks()
        # enumerate all tasks
        for task in all_tasks:
            # request the task cancel
            task.cancel()
        # wait for all tasks to cancel
        await asyncio.gather(*all_tasks, return_exceptions=True)
    loop = asyncio.get_running_loop()
    loop.run_until_complete(cancel_all_tasks())



if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
    )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        hs_file.close()
        bp_file.close()
