import asyncio
import logging
import time
import threading
from queue import Queue, Empty
from collections import deque
from typing import Union

import dearpygui.dearpygui as dpg
from bleak import BleakScanner, BleakClient, BLEDevice, BleakGATTCharacteristic
import numpy as np

SERVER_NAME = "ESP_SPP_SERVER"
HS_CHAR_UUID = "cdd4c6c4-7a3c-599b-324e-f93750d2f002"
VREF = 5.0
MAX_DATA_LEN = 200

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
)

def receive_data(queue: Queue):
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
                if HS_CHAR_UUID == char.uuid:
                    hs_char = char
        return hs_char

    def notification_callback(char: BleakGATTCharacteristic, data: bytearray):
        val = int.from_bytes(bytes=data, byteorder='little', signed=False)
        queue.put_nowait(val)
        logger.info(f"{data} {val} {(val / 4096.0 * VREF):.3f}");

    async def main():
        loop = asyncio.get_running_loop()
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
            await client.start_notify(hs_char, notification_callback)
            while True:
                if not client.is_connected:
                    break
                await asyncio.sleep(1)

    asyncio.run(main())

queue = Queue()
start_time = time.perf_counter()
time_data = deque(maxlen=MAX_DATA_LEN)
hs_data = deque(maxlen=MAX_DATA_LEN)
bp_data = deque(maxlen=MAX_DATA_LEN)

def update_plot():
    global queue, start_time, time_data, hs_data, bp_data
    try:
        val = queue.get_nowait()
        # logger.info(f'get {val}')
    except Empty:
        return
    time_data.append(time.perf_counter() - start_time)
    hs_data.append(val)
    updated_data_x = np.array(time_data)
    updated_data_y = np.array(hs_data) / 4096.0 * VREF
    dpg.configure_item('heart_sound', x=updated_data_x, y=updated_data_y)
    # logger.info('set value successfully')
    if dpg.get_value('auto_fit_checkbox'):
        dpg.fit_axis_data('x_axis')
        # dpg.set_axis_limits_auto('y_axis')

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

recv_data_handler = threading.Thread(target=receive_data, args=(queue,),daemon=True)
recv_data_handler.start()

# dpg.start_dearpygui()
while dpg.is_dearpygui_running():
    if queue.qsize() > 0:
        update_plot() # updating the plot directly from the running loop
    dpg.render_dearpygui_frame()
dpg.destroy_context()
