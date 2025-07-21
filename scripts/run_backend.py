import asyncio
from config_manager import load_config
from logger import get_logger
from tcp_server import start_tcp_server
from udp_server import start_udp_server
from serial_server import start_serial_server

async def main():
    config = load_config()
    log_format = config["logging"]["format"]
    log_level = config["logging"]["level"]

    tasks = []

    if config["tcp"]["enabled"]:
        logger = get_logger("tcp", timestamp_format=log_format, level=log_level)
        tasks.append(start_tcp_server(
            config["tcp"]["host"],
            config["tcp"]["port"],
            logger
        ))

    if config["udp"]["enabled"]:
        logger = get_logger("udp", timestamp_format=log_format, level=log_level)
        tasks.append(start_udp_server(
            config["udp"]["host"],
            config["udp"]["port"],
            logger
        ))

    if config["serial"]["enabled"]:
        logger = get_logger("serial", timestamp_format=log_format, level=log_level)
        tasks.append(start_serial_server(
            config["serial"]["port"],
            config["serial"]["baudrate"],
            logger
        ))

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())