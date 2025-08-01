import socket
import threading
from datetime import datetime
import os

HOST = '10.2.7.120'
PORT = 1235

script_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(script_dir, f"tcp_{PORT}.txt")

def log(msg):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_message = f"{timestamp} {msg}"
    print(full_message)
    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(full_message + "\n")

def handle_client(conn, addr):
    log(f"Connected {addr[0]}.")
    while True:
        try:
            data = conn.recv(1024)
            if not data:
                break
            hex_data = ' '.join(f'{b:02X}' for b in data)
            log(f"{addr[0]}: {hex_data}")
        except ConnectionResetError:
            log(f"Client {addr} has disconnected.")
    conn.close()
    log(f"Disconnected {addr[0]}.")

def start_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind((HOST, PORT))
        server_socket.listen(5)
        server_socket.settimeout(1.0)
        log(f"Server listening on {HOST}:{PORT}")
                
        while True:
            try:
                conn, addr = server_socket.accept()
                thread = threading.Thread(target=handle_client, args=(conn, addr))
                thread.start()
            except socket.timeout:
                continue

if __name__ == "__main__":
    start_server()