import asyncio
import serial_asyncio
from logger import get_logger

class SerialProtocol(asyncio.Protocol):
    def __init__(self, logger):
        self.logger = logger

    def connection_made(self, transport):
        self.transport = transport
        self.logger.info("Serial connection opened")

    def data_received(self, data):
        message = data.decode(errors='ignore')
        self.logger.info(f"Serial received: {message}")

async def start_serial_server(port, baudrate, logger):
    loop = asyncio.get_running_loop()
    transport, protocol = await serial_asyncio.create_serial_connection(
        loop, lambda: SerialProtocol(logger), port, baudrate=baudrate
    )
    logger.info(f"Serial server started on {port} at {baudrate} baud")
    return transport, protocol