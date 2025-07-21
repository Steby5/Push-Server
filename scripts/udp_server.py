import asyncio
from logger import get_logger

class UDPServerProtocol(asyncio.DatagramProtocol):
    def __init__(self, logger):
        self.logger = logger

    def datagram_received(self, data, addr):
        message = data.decode()
        self.logger.info(f"UDP received from {addr}: {message}")

async def start_udp_server(host, port, logger):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UDPServerProtocol(logger),
        local_addr=(host, port)
    )
    logger.info(f"UDP server started on {host}:{port}")
    return transport, protocol