import asyncio
from datetime import datetime
import os
import aioserial

script_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(script_dir, "logs.txt")

def log(msg):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_message = f"{timestamp} {msg}"
    print(full_message)
    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(full_message + "\n")

async def read_and_print(aioserial_instance: aioserial.AioSerial):
    port = aioserial_instance.port
    while True:
        data = await aioserial_instance.read_until_async()
        message = data.decode('utf-8', errors='replace').strip()
        log(f"{port} {message}")

asyncio.run(read_and_print(aioserial.AioSerial(port='COM15', baudrate=115200, bytesize=8, parity=aioserial.PARITY_NONE, stopbits=1)))