import asyncio
from logger import get_logger

class TCPServerProtocol(asyncio.Protocol):
    def __init__(self, logger):
        self.logger = logger

    def connection_made(self, transport):
        self.transport = transport
        peername = transport.get_extra_info('peername')
        self.logger.info(f"TCP connection from {peername}")

    def data_received(self, data):
        message = data.decode()
        self.logger.info(f"TCP received: {message}")
        self.transport.write(data)

async def start_tcp_server(host, port, logger):
    loop = asyncio.get_running_loop()
    server = await loop.create_server(
        lambda: TCPServerProtocol(logger),
        host, port
    )
    logger.info(f"TCP server started on {host}:{port}")
    return server
