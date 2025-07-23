import asyncio
import json
import os
import sys
from datetime import datetime
import serial_asyncio

CONFIG_PATH = "config/config.json"

class TCPService:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.running = False
        self.server = None

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        self.logger(f"TCP connection from {addr}", level="event")
        try:
            while self.running:
                data = await reader.read(100)
                if not data:
                    break
                message = data.decode()
                self.logger(f"Received: {message}")
                writer.write(data)
                await writer.drain()
        except Exception as e:
            self.logger(f"TCP error: {e}", level="error")
        finally:
            writer.close()
            await writer.wait_closed()
            self.logger(f"TCP connection closed: {addr}", level="event")

    async def start(self):
        self.running = True
        self.server = await asyncio.start_server(
            self.handle_client,
            self.config.get("host", "127.0.0.1"),
            self.config.get("port", 9000)
        )
        self.logger(f"TCP server running on {self.config['host']}:{self.config['port']}", level="event")
        async with self.server:
            await self.server.serve_forever()

    async def stop(self):
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()

class UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, logger):
        self.logger = logger

    def connection_made(self, transport):
        self.transport = transport
        self.logger("UDP server started", level="event")

    def datagram_received(self, data, addr):
        message = data.decode()
        self.logger(f"Received {message} from {addr}")
        self.transport.sendto(data, addr)

    def error_received(self, exc):
        self.logger(f"UDP error: {exc}", level="error")

    def connection_lost(self, exc):
        self.logger("UDP server closed", level="event")

class UDPService:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.running = False
        self.transport = None

    async def start(self):
        self.running = True
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: UDPProtocol(self.logger),
            local_addr=(self.config.get("host", "127.0.0.1"), self.config.get("port", 9001))
        )

    async def stop(self):
        self.running = False
        if self.transport:
            self.transport.close()

class SerialService:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.running = False
        self.transport = None
        self.protocol = None

    class SerialProtocol(asyncio.Protocol):
        def __init__(self, logger):
            self.logger = logger
            self.buffer = b""

        def connection_made(self, transport):
            self.transport = transport
            self.logger("Serial connection established", level="event")

        def data_received(self, data):
            self.buffer += data
            message = data.decode(errors='ignore')
            self.logger(f"Serial received: {message}")

        def connection_lost(self, exc):
            self.logger("Serial connection closed", level="event")

    async def start(self):
        self.running = True
        loop = asyncio.get_running_loop()
        self.transport, self.protocol = await serial_asyncio.create_serial_connection(
            loop,
            lambda: SerialService.SerialProtocol(self.logger),
            self.config.get("port", "COM3"),
            baudrate=self.config.get("baudrate", 9600)
        )

    async def stop(self):
        self.running = False
        if self.transport:
            self.transport.close()

class ServiceManager:
    def __init__(self, config_path=CONFIG_PATH):
        self.config_path = config_path
        self.logger = self._make_logger("main")
        self.services = {}
        self.tasks = {}
        self.config = self.load_config()

    def load_config(self):
        if not os.path.exists(self.config_path):
            default_config = {
                "debug": False,
                "theme": "light",
                "services": {
                    "tcp": {"enabled": False, "host": "127.0.0.1", "port": 9000},
                    "udp": {"enabled": False, "host": "127.0.0.1", "port": 9001},
                    "serial": {"enabled": False, "port": "COM3", "baudrate": 9600}
                }
            }
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, 'w') as f:
                json.dump(default_config, f, indent=4)
            return default_config
        else:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)

    async def start_services(self):
        for name, type_, settings in self.config.get("services", {}).items():
            if settings.get("enabled"):
                await self.start_service(name, type_, settings)

    async def start_service(self, name, type_, settings):
        if name in self.services:
            self.logger(f"{name} is already running.")
            return

        if type_ == "tcp":
            service = TCPService(settings, self._make_logger(name))
        elif type_ == "udp":
            service = UDPService(settings, self._make_logger(name))
        elif type_ == "serial":
            service = SerialService(settings, self._make_logger(name))
        else:
            self.logger(f"Unknown service type: {type_}", level="error")
            return

        self.services[name] = service
        self.tasks[name] = asyncio.create_task(service.start())
        self.logger(f"Service {name} ({type_}) started.", level="event")

    async def stop_service(self, name):
        service = self.services.get(name)
        task = self.tasks.get(name)
        if service and task:
            await service.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self.services[name]
            del self.tasks[name]
            self.logger(f"Service {name} stopped.", level="event")
        else:
            self.logger(f"{name} is not running.", level="warning")

    async def stop_all_services(self):
        for name in list(self.services.keys()):
            await self.stop_service(name)
        self.logger("All services stopped.")

    def _make_logger(self, name):
        def logger(message, level="normal"):
            timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
            log_line = f"{timestamp} {message}"
            if level == "error":
                print(f"\33[41m{log_line}\033[0m", file=sys.stderr)
            elif level == "warning":
                print(f"\33[43m{log_line}\033[0m", file=sys.stderr)
            elif level == "event":
                print(f"\33[34m{log_line}\033[0m", file=sys.stderr)
            else:
                print(log_line)
            with open(f"{name}_log.txt", "a") as f:
                f.write(log_line + "\n")
        return logger
async def main():
    manager = ServiceManager()
    await manager.start_services()
    await asyncio.sleep(5)
    await manager.stop_all_services()

if __name__ == "__main__":
    asyncio.run(main())