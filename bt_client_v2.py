import asyncio
import logging
import csv
from datetime import datetime
import time
import threading
from queue import Queue, Empty
from collections import deque
from enum import Enum
from typing import Union

import dearpygui.dearpygui as dpg
from bleak import BleakScanner, BleakClient, BLEDevice, BleakGATTCharacteristic

SERVER_NAME = "ESP_SPP_SERVER"
HS_CHAR_UUID = "cdd4c6c4-7a3c-599b-324e-f93750d2f002"
BP_CHAR_UUID = "cdd4c6c4-7a3c-599b-324e-f93750d2f003"
VREF = 5.0
MAX_DATA_LEN = 200

class BIOSIG(Enum):
    HS = 0
    BP = 1

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
)

def receive_data(queue: Queue, stop_event: threading.Event):
    async def discover_server() -> Union[BLEDevice, None]:
        server = None
        devices = await BleakScanner.discover()
        logger.info("list of available devices:")
        for device in devices:
            logger.info("[Device] %s", device)
            if device.name == SERVER_NAME:
                server = device
        return server

    async def extract_all_services(client: BleakClient):
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

                for descriptor in char.descriptors:
                    try:
                        value = await client.read_gatt_descriptor(descriptor.handle)
                        logger.info("    [Descriptor] %s, Value: %r", descriptor, value)
                    except Exception as e:
                        logger.error("    [Descriptor] %s, Error: %s", descriptor, e)

    async def find_hs_service(client: BleakClient) -> Union[BleakGATTCharacteristic, None]:
        hs_char = None
        for service in client.services:
            for char in service.characteristics:
                if char.uuid == HS_CHAR_UUID:
                    hs_char = char
        return hs_char

    async def find_bp_service(client: BleakClient) -> Union[BleakGATTCharacteristic, None]:
        bp_char = None
        for service in client.services:
            for char in service.characteristics:
                if char.uuid == BP_CHAR_UUID:
                    bp_char = char
        return bp_char

    async def notification_callback(char: BleakGATTCharacteristic, data: bytearray):
        val = int.from_bytes(bytes=data, byteorder='little', signed=False)
        if char.uuid == HS_CHAR_UUID:
            sig_type = BIOSIG.HS
        elif char.uuid == BP_CHAR_UUID:
            sig_type = BIOSIG.BP
        else:
            sig_type = None
        queue.put_nowait((sig_type, val))
        logger.info(f"{sig_type} {data} {val} {(val / 4096.0 * VREF):.3f}");

    async def main():
        server = await discover_server()
        if server:
            logger.info("found %s", server.name)
        else:
            logger.error("not found %s", SERVER_NAME)
            return
        async with BleakClient(address_or_ble_device=server, winrt=dict(use_cached_services=False)) as client:
            logger.info("connected to %s", server.name)
            logger.info("begin to extract all of its services")
            await extract_all_services(client)
            hs_char = await find_hs_service(client)
            bp_char = await find_bp_service(client)
            await client.start_notify(hs_char, notification_callback)
            await client.start_notify(bp_char, notification_callback)
            while not stop_event.is_set():
                if not client.is_connected:
                    break
                await asyncio.sleep(1)

    asyncio.run(main())

def update_plot(queue: Queue, stop_event: threading.Event):

    start_time = time.perf_counter()
    time_data = deque(maxlen=MAX_DATA_LEN)
    hs_data = deque(maxlen=MAX_DATA_LEN)
    bp_data = deque(maxlen=MAX_DATA_LEN)

    file_date = f'{datetime.now().strftime('%d_%m_%Y_%H_%M')}'
    hs_file = open(f'{file_date}_{BIOSIG.HS.name}.csv', 'w', newline='')
    bp_file = open(f'{file_date}_{BIOSIG.BP.name}.csv', 'w', newline='')
    hs_log_writer = csv.writer(hs_file, dialect='excel')
    bp_log_writer = csv.writer(bp_file, dialect='excel')
    while not stop_event.is_set():
        try:
            sig_type, val = queue.get_nowait()
            # logger.info(f'get {val}')
        except Empty:
            continue
        delta_t = time.perf_counter() - start_time
        time_data.append(delta_t)
        data_x = list(time_data)
        if sig_type == BIOSIG.HS:
            hs_data.append(val)
            hs_data_y = [x / 4096.0 * VREF for x in list(hs_data)]
            dpg.configure_item('heart_sound', x=data_x, y=hs_data_y)
            hs_log_writer.writerow([delta_t, val])
        if sig_type == BIOSIG.BP:
            bp_data.append(val)
            bp_data_y = [x / 4096.0 * VREF for x in list(bp_data)]
            dpg.configure_item('blood_pressure', x=data_x, y=bp_data_y)
            bp_log_writer.writerow([delta_t, val])
        # logger.info('set value successfully')
        if dpg.get_value('auto_fit_checkbox'):
            dpg.fit_axis_data('x_axis')
            # dpg.set_axis_limits_auto('y_axis')
    else:
        hs_file.close()
        bp_file.close()

queue = Queue()
stop_event = threading.Event()

dpg.create_context()

with dpg.window(label='plotter window', tag='primary_window', no_scrollbar=True):
    with dpg.plot(label='heart sound and blood pressure series', height=-25, width=-1):
        dpg.add_plot_legend()

        dpg.add_plot_axis(dpg.mvXAxis, label='x', tag='x_axis')
        dpg.add_plot_axis(dpg.mvYAxis, label='y', tag='y_axis')
        dpg.set_axis_limits('y_axis', ymin=-3.0, ymax=3.0)

        dpg.add_line_series([], [], label='heart sound', parent='y_axis', tag='heart_sound')
        dpg.add_button(label='delete heart sound series', parent=dpg.last_item(), callback=lambda: dpg.delete_item('heart_sound'))

        dpg.add_line_series([], [], label='blood pressure', parent='y_axis', tag='blood_pressure')
        dpg.add_button(label='delete blood pressure series', parent=dpg.last_item(), callback=lambda: dpg.delete_item('blood_pressure'))
    dpg.add_checkbox(label="Auto fit x axis limits", tag='auto_fit_checkbox', default_value=True, before='heart sound and blood pressure series')

dpg.create_viewport(title='Plotter', height=600, width=600)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.set_primary_window('primary_window', True)

recv_data_handler = threading.Thread(target=receive_data, args=(queue, stop_event))
recv_data_handler.start()

update_plot_handler = threading.Thread(target=update_plot, args=(queue,stop_event))
update_plot_handler.start()

dpg.start_dearpygui()
# while dpg.is_dearpygui_running():
#     if queue.qsize() > 0:
#         update_plot() # updating the plot directly from the running loop
#     dpg.render_dearpygui_frame()
stop_event.set()
dpg.destroy_context()
