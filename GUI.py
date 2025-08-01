import asyncio
import os
import json
import select
import socket
import threading
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import queue
import aioserial

gui_log_queue = queue.Queue()

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "Push_Server_conf.json")

tcp_setup = {
    "interface": "0.0.0.0",
    "port": 1234,
    "timeout": 20,
    "max_conn": 1,
    "file": os.path.join(script_dir, "tcp_log.txt")
}

udp_setup = {
    "interface": "0.0.0.0",
    "port": 1234,
    "file": os.path.join(script_dir, "udp_log.txt")
}

serial_setup = {
    "interface": None,
    "baud": "9600",
    "parity": "None",
    "databits": "8",
    "stopbits": "1",
    "file": os.path.join(script_dir, "serial_log.txt")
}

def get_local_ips():
    ips = ["0.0.0.0"]
    try:
        hostname = socket.gethostname()
        ips.append(socket.gethostbyname(hostname))
    except:
        pass
    return list(set(ips))

def validate_port(port):
    try:
        port = int(port)
        return 1 <= port <= 65535
    except:
        return False

def validate_hex_string(s):
    try:
        bytes.fromhex(s.replace(" ", ""))
        return True
    except ValueError:
        return False

def validate_file_path(path):
    return bool(path and isinstance(path, str))

def read_config(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def write_config(path, config):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, sort_keys=True)

milis = read_config(config_path).get("milis", False)

def unified_log(message, log_file=None, gui_callback=None):
    if milis:
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S.%f]")[:-3]
    else:
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_message = f"{timestamp} {message}"
    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(full_message + "\n")
    if gui_callback:
        gui_callback(full_message)

class SerialServerThread:
    def __init__(self, port, baudrate, bytesize, parity, stopbits, log_file, log_callback):
        #super().__init__(daemon=True)
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.log_file = log_file
        self.log_callback = log_callback
        self._running = threading.Event()
        self._running.set()
        self._task = None
        self._loop = None
        self._aioserial = None

    def start(self):
        self._loop = asyncio.new_event_loop()
        #self._task = threading.Thread(target=self._loop_runner, deamon=True)
        self._task = threading.Thread(target=self._loop_runner)
        self._task.start()

    def _loop_runner(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self.run())
        
    async def run(self):
        try:
            self._aioserial = aioserial.AioSerial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.bytesize,
                parity=self.parity,
                stopbits=self.stopbits,
                timeout=0
            )
            self._aioserial.reset_input_buffer()
            unified_log(
                f"Serial port {self.port} opened at {self.baudrate} baud",
                log_file=self.log_file,
                gui_callback=lambda msg: self.log_callback(msg + "\n", "status") if self.log_callback else None
            )
            while self._running.is_set():
                try:
                    data = await self._aioserial.readline_async()
                    if data:
                        line = data.decode(errors='ignore').strip()
                        unified_log(
                            f"{self.port} {line}",
                            log_file=self.log_file,
                            gui_callback=self.log_callback
                        )
                except Exception as e:
                    unified_log(
                        f"{self.port} Error reading data: {e}",
                        log_file=self.log_file,
                        gui_callback=self.log_callback
                    )
                    break
        except Exception as e:
            unified_log(
                f"Error opening serial port {self.port}: {e}",
                log_file=self.log_file,
                gui_callback=self.log_callback
            )

    def stop(self):
        unified_log(
            f"Stopping serial server on {self.port}",
            log_file=self.log_file,
            gui_callback=lambda msg: self.log_callback(msg + "\n", "status") if self.log_callback else None
        )
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._running.stop)
            if self._aioserial:
                self._aioserial.close()

class TCPServerThread(threading.Thread):
    def __init__(self, interface, port, timeout, max_connections, log_file, log_callback, test_mode=False):
        super().__init__(daemon=True)
        self.interface = interface
        self.port = port
        self.timeout = timeout
        self.max_connections = max_connections
        self.log_file = log_file
        self.log_callback = log_callback
        self.test_mode = test_mode
        self._running = threading.Event()
        self._running.set()

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.interface, self.port))
            s.listen(self.max_connections)
            s.settimeout(1.0)

            unified_log(
                f"Listening on {self.interface}:{self.port}, timeout: {self.timeout}s, max. connections: {self.max_connections}",
                log_file=self.log_file,
                gui_callback=lambda msg: self.log_callback(msg + "\n", "status") if self.log_callback else None
            )

            while self._running.is_set():
                try:
                    conn, addr = s.accept()
                    unified_log(
                        f"{addr[0]} Connected",
                        log_file=self.log_file,
                        gui_callback=lambda msg: self.log_callback(msg + "\n", "status") if self.log_callback else None
                    )
                    with conn:
                        total_bytes = 0
                        while self._running.is_set():
                            ready = select.select([conn], [], [], self.timeout)
                            if ready[0]:
                                try:
                                    data = conn.recv(1024)
                                    if not data:
                                        break

                                    total_bytes += len(data)
                                    hex_data = ' '.join(f'{b:02X}' for b in data)
                                    unified_log(
                                        f"{addr[0]} {hex_data}",
                                        log_file=self.log_file,
                                        gui_callback=lambda msg: self.log_callback(msg + "\n", "normal") if self.log_callback else None
                                    )

                                    if self.test_mode and total_bytes > 10:
                                        unified_log(
                                            f"{addr[0]} Test mode: Closing connection after 10 bytes",
                                            log_file=self.log_file,
                                            gui_callback=lambda m: self.log_callback(m + "\n", "warning") if self.log_callback else None
                                        )
                                        break

                                except Exception as e:
                                    unified_log(
                                        f"{addr[0]} Error receiving data: {e}",
                                        log_file=self.log_file,
                                        gui_callback=lambda m: self.log_callback(m + "\n", "error") if self.log_callback else None
                                    )
                                    break
                            else:
                                unified_log(
                                    f"{addr[0]} Disconnected (timed out)",
                                    log_file=self.log_file,
                                    gui_callback=lambda m: self.log_callback(m + "\n", "warning") if self.log_callback else None
                                )
                                break

                except socket.timeout:
                    continue
                except Exception as e:
                    unified_log(
                        f"Error: {e}",
                        log_file=self.log_file,
                        gui_callback=lambda m: self.log_callback(m + "\n", "error") if self.log_callback else None
                    )

    def stop(self):
        self._running.clear()

class UDPServerThread(threading.Thread):
    def __init__(self, interface, port, log_file, log_callback):
        super().__init__(daemon=True)
        self.interface = interface
        self.port = port
        self.log_file = log_file
        self.log_callback = log_callback
        self._running = threading.Event()
        self._running.set()

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.interface, self.port))
            s.settimeout(1.0)

            unified_log(
                f"Listening on {self.interface}:{self.port}",
                log_file=self.log_file,
                gui_callback=lambda m: self.log_callback(m + "\n", "status") if self.log_callback else None
            )

            while self._running.is_set():
                try:
                    data, addr = s.recvfrom(1024)
                    hex_data = ' '.join(f'{b:02X}' for b in data)
                    unified_log(
                        f"{addr[0]} {hex_data}",
                        log_file=self.log_file,
                        gui_callback=self.log_callback
                    )
                    continue
                except Exception as e:
                    unified_log(
                        f"Error: {e}",
                        log_file=self.log_file,
                        gui_callback=lambda m: self.log_callback(m + "\n", "error") if self.log_callback else None
                    )

    def stop(self):
        self._running.clear()

def create_server_frame(parent, title, default_file, service_type="tcp"):
    frame = ttk.Frame(parent, padding=10)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(4, weight=1)

    header_frame = ttk.Frame(frame)
    header_frame.grid(row=0, column=0, sticky='ew', pady=(0, 5))
    header_frame.columnconfigure(2, weight=1)

    label = ttk.Label(header_frame, text=title, font=('Helvetica', 12, 'bold'), padding=(10, 5))
    label.grid(row=0, column=0, sticky='w')

    status_label = ttk.Label(header_frame, text="🔴 Stopped", font=('Helvetica', 12, 'bold'), foreground='red')
    status_label.grid(row=0, column=2, sticky='e', padx=10)

    input_frame = ttk.Frame(frame)
    input_frame.grid(row=1, column=0, sticky='ew', pady=5)

    file_frame = ttk.Frame(frame)
    file_frame.grid(row=2, column=0, sticky='ew', pady=5)
    file_frame.columnconfigure(1, weight=1)

    ttk.Label(file_frame, text="Output File:").grid(row=0, column=0, sticky='w')
    file_entry = ttk.Entry(file_frame)
    file_entry.insert(0, os.path.join(script_dir, default_file))
    file_entry.grid(row=0, column=1, sticky='ew', padx=5)

    def browse_file():
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialdir=script_dir,
            initialfile=default_file,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            file_entry.delete(0, 'end')
            file_entry.insert(0, file_path)

    ttk.Button(file_frame, text="Browse", command=browse_file).grid(row=0, column=2, padx=5)

    if service_type == "tcp":
        test_mode = tk.BooleanVar(value=False)
        ttk.Checkbutton(file_frame, text="Test", variable=test_mode, bootstyle="warning-round-toggle").grid(row=0, column=3, padx=(0, 5))

    def clear_log():
        text_widget.config(state='normal')
        text_widget.delete('1.0', tk.END)
        text_widget.config(state='disabled')

    ttk.Button(file_frame, text="Clear Log", command=clear_log, bootstyle="danger").grid(row=0, column=4, padx=(0, 5))

    text_frame = ttk.Frame(frame)
    text_frame.grid(row=4, column=0, sticky='nsew', pady=(5, 0))
    frame.rowconfigure(4, weight=1)
    text_widget = scrolledtext.ScrolledText(text_frame, wrap='word', height=6)


    text_widget.pack(fill='both', expand=True)
    text_widget.tag_config("error", foreground="red")
    text_widget.tag_config("partial", foreground="gray", font=("TkDefaultFont", 9, "italic"))
    text_widget.tag_config("status", foreground="green")

    tcp_thread = None
    udp_thread = None
    serial_thread = None

    def refresh_ports(interface_combo):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        interface_combo['values'] = ports
        if ports:
            interface_combo.set(ports[0])

    def log_callback(msg, tag=None):
        if tag is None:
            lower_msg = msg.lower()
            if "error" in lower_msg or "fail" in lower_msg:
                tag = "error"
            elif "[partial]" in lower_msg:
                tag = "partial"
            elif "listening" in lower_msg:
                tag = "status"
            else:
                tag = "normal"

        unified_log(msg, log_file=file_entry.get())
        text_widget.config(state='normal')
        text_widget.insert('end', msg + '\n', tag)
        text_widget.see('end')
        text_widget.config(state='disabled')

    def toggle_server():
        nonlocal tcp_thread, udp_thread, serial_thread
        if switch.instate(['selected']):
            if service_type == "tcp":
                interface = interface_combo.get()
                port = port_spinbox.get()
                if not validate_port(port):
                    messagebox.showerror("Input Error", "Invalid TCP port number.")
                    switch.state(['!selected'])
                    return
                try:
                    timeout = int(timeout_entry.get())
                    max_conn = int(max_conn_entry.get())
                    server_thread = TCPServerThread(interface, int(port), timeout, max_conn, file_entry.get(), log_callback, test_mode.get())
                    server_thread.start()
                    status_label.config(text="🟢 Running", foreground='green')
                except Exception as e:
                    messagebox.showerror("Server Error", str(e))
                    switch.state(['!selected'])

            elif service_type == "udp":
                interface = interface_combo.get()
                port = port_spinbox.get()
                if not validate_port(port):
                    messagebox.showerror("Input Error", "Invalid TCP port number.")
                    switch.state(['!selected'])
                    return
                try:
                    server_thread = UDPServerThread(interface, port, file_entry.get(), log_callback)
                    server_thread.start()
                    status_label.config(text="🟢 Running", foreground='green')
                except Exception as e:
                    messagebox.showerror("Server Error", str(e))
                    switch.state(['!selected'])

            elif service_type == "serial":
                try:
                    interface = interface_combo.get()
                    baud = int(baud_combo.get())
                    parity = parity_combo.get()
                    if parity == "None":
                        parity = "N"
                    databits = int(databits_combo.get())
                    stopbits = float(stopbits_combo.get())
                    output_file = file_entry.get()
                    server_thread = SerialServerThread(interface, baud, databits, parity, stopbits, output_file, log_callback)
                    server_thread.start()
                    status_label.config(text="🟢 Running", foreground='green')
                except Exception as e:
                    messagebox.showerror("Server Error", str(e))
                    switch.state(['!selected'])
        else:
            status_label.config(text="🔴 Stopped", foreground='red')
            if tcp_thread:
                tcp_thread.stop()
            elif udp_thread:
                udp_thread.stop()
            elif serial_thread:
                serial_thread.stop()

    switch = ttk.Checkbutton(header_frame, bootstyle="success-round-toggle", command=toggle_server)
    switch.grid(row=0, column=1, padx=(10, 5), ipadx=10, ipady=5)

    if service_type == "serial":
        ttk.Label(input_frame, text="Interface:").grid(row=0, column=0, sticky='w')
        interface_combo = ttk.Combobox(input_frame, values=[], width=10)
        interface_combo.grid(row=0, column=1, sticky='w')
        refresh_ports(interface_combo)
        ttk.Button(input_frame, text="↻", width=3, command=lambda: refresh_ports(interface_combo)).grid(row=0, column=2, padx=(5, 10))
        ttk.Label(input_frame, text="Baud Rate:").grid(row=0, column=3, sticky='w', padx=(10, 0))
        baud_combo = ttk.Combobox(input_frame, values=[
            "110", "300", "600", "1200", "2400", "4800", "9600", "14400", "19200", "28800",
            "38400", "56000", "57600", "115200", "128000", "230400", "250000", "460800", "921600"
        ], width=8)
        baud_combo.set("9600")
        baud_combo.grid(row=0, column=4, sticky='w')

        ttk.Label(input_frame, text="Parity:").grid(row=0, column=5, sticky='w', padx=(10, 0))
        parity_combo = ttk.Combobox(input_frame, values=["None", "Even", "Odd", "Mark", "Space"], width=8)
        parity_combo.set("None")
        parity_combo.grid(row=0, column=6, sticky='w')

        ttk.Label(input_frame, text="Data Bits:").grid(row=0, column=7, sticky='w', padx=(10, 0))
        databits_combo = ttk.Combobox(input_frame, values=["5", "6", "7", "8"], width=2)
        databits_combo.set("8")
        databits_combo.grid(row=0, column=8, sticky='w')

        ttk.Label(input_frame, text="Stop Bits:").grid(row=0, column=9, sticky='w', padx=(10, 0))
        stopbits_combo = ttk.Combobox(input_frame, values=["1", "1.5", "2"], width=2)
        stopbits_combo.set("1")
        stopbits_combo.grid(row=0, column=10, sticky='w')

        return frame, {
            "interface": interface_combo,
            "baud": baud_combo,
            "parity": parity_combo,
            "databits": databits_combo,
            "stopbits": stopbits_combo,
            "file_entry": file_entry,
            "text_widget": text_widget,
            "status_label": status_label,
            "switch": switch
        }
    else:
        ttk.Label(input_frame, text="Interface:").grid(row=0, column=0, sticky='w')
        interface_combo = ttk.Combobox(input_frame, values=get_local_ips(), width=15)
        interface_combo.set("0.0.0.0")
        interface_combo.grid(row=0, column=1, sticky='w')

        ttk.Label(input_frame, text="Port:").grid(row=0, column=2, sticky='w', padx=(10, 0))
        port_spinbox = ttk.Spinbox(input_frame, from_=1, to=65535, width=8)
        port_spinbox.insert(0, "1234")
        port_spinbox.grid(row=0, column=3, sticky='w')

        if service_type == "tcp":
            ttk.Label(input_frame, text="Timeout (s):").grid(row=0, column=6, sticky='w', padx=(10, 0))
            timeout_entry = ttk.Spinbox(input_frame, from_=1, to=9999, width=6)
            timeout_entry.insert(0, "20")
            timeout_entry.grid(row=0, column=7, sticky='w')

            ttk.Label(input_frame, text="Max Conn:").grid(row=0, column=8, sticky='w', padx=(10, 0))
            max_conn_entry = ttk.Spinbox(input_frame, from_=1, to=1000, width=6)
            max_conn_entry.insert(0, "1")
            max_conn_entry.grid(row=0, column=9, sticky='w')
        else:
            timeout_entry = None
            max_conn_entry = None

        return frame, {
        "interface": interface_combo,
        "port": port_spinbox,
        "timeout": timeout_entry if service_type == "tcp" else None,
        "max_conn": max_conn_entry if service_type == "tcp" else None,
        "file_entry": file_entry,
        "text_widget": text_widget,
        "status_label": status_label,
        "switch": switch
    }
    
def open_layout_config_window(root, main_frame, frame_refs):

    def save_and_apply():
        config = read_config(config_path)

        config["layout"] = {
            "visible": {k: var.get() for k, var in visibility_vars.items()},
            "template": layout_var.get()
        }

        write_config(config_path, config)
        apply_layout(main_frame, frame_refs, config["layout"])
        win.destroy()

    win = tk.Toplevel(root)
    win.title("Layout Configuration")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            existing_config = json.load(f)
    except Exception:
        existing_config = {"visible": {}, "template": "vertical"}

    visibility_vars = {}
    for i, name in enumerate(frame_refs):
        default_visible = existing_config.get("visible", {}).get(name, True)
        visibility_vars[name] = tk.BooleanVar(value=default_visible)
        ttk.Checkbutton(win, text=f"Show {name.upper()}", variable=visibility_vars[name]).grid(row=i, column=0, sticky="w")

    ttk.Label(win, text="Layout Style:").grid(row=0, column=2, padx=10)
    layout_var = tk.StringVar(value=existing_config.get("template", "vertical"))
    layout_options = ["vertical", "horizontal"]
    layout_menu = ttk.OptionMenu(win, layout_var, layout_var.get(), *layout_options)
    layout_menu.grid(row=0, column=3, padx=10)

    ttk.Button(win, text="Apply", command=save_and_apply).grid(row=len(frame_refs)+1, column=0, columnspan=4, pady=10)

def apply_layout(main_frame, frame_refs, config):
    for widget in main_frame.winfo_children():
        widget.grid_forget()

    layout = config.get("template", "vertical")
    visible = config.get("visible", {})

    for i in range(len(frame_refs)):
        main_frame.rowconfigure(i, weight=0)
        main_frame.columnconfigure(i, weight=0)

    if layout == "horizontal":
        main_frame.rowconfigure(0, weight=1)
        col = 0
        for name in frame_refs:
            if visible.get(name, True):
                main_frame.columnconfigure(col, weight=1)
                frame_refs[name].grid(row=0, column=col, sticky="nsew", padx=10, pady=5)
                col += 1
    else:  # vertical
        main_frame.columnconfigure(0, weight=1)
        row = 0
        for name in frame_refs:
            if visible.get(name, True):
                main_frame.rowconfigure(row, weight=1)
                frame_refs[name].grid(row=row, column=0, sticky="nsew", padx=10, pady=5)
                row += 1

def open_tcp_client():
    win = tk.Toplevel()
    win.title("TCP Client")

    ttk.Label(win, text="IP:").grid(row=0, column=0, sticky='w', padx=(10, 0))
    ip_entry = ttk.Entry(win, width=12)
    ip_entry.insert(0, "127.0.0.1")
    ip_entry.grid(row=0, column=1, sticky='w')

    ttk.Label(win, text="Port:").grid(row=1, column=0, sticky='w', padx=(10, 0))
    port_entry = ttk.Entry(win, width=8)
    port_entry.insert(0, "1234")
    port_entry.grid(row=1, column=1, sticky='w')

    ttk.Label(win, text="Message:").grid(row=2, column=0, sticky='w', padx=(10, 0))
    msg_entry = ttk.Entry(win, width=40)
    msg_entry.grid(row=2, column=1, sticky='w')

    ttk.Label(win, text="Close String:").grid(row=3, column=0, sticky='w', padx=(10, 0))
    close_entry = ttk.Entry(win, width=40)
    close_entry.grid(row=3, column=1, sticky='w')

    output = scrolledtext.ScrolledText(win, height=6, state='disabled')
    output.grid(row=5, column=0, columnspan=4, pady=5, sticky='nsew')

    client_socket = None
    stop_event = threading.Event()

    def receive_tcp():
        while not stop_event.is_set():
            try:
                data = client_socket.recv(1024)
                if data:
                    output.config(state='normal')
                    output.insert('end', f"Received: {data.decode(errors='ignore')}\n")
                    output.see('end')
                    output.config(state='disabled')
                else:
                    break
            except:
                break

    def connect_tcp():
        nonlocal client_socket
        try:
            client_socket = socket.create_connection((ip_entry.get(), int(port_entry.get())))
            threading.Thread(target=receive_tcp, daemon=True).start()
            output.config(state='normal')
            output.insert('end', "Connected to server.\n")
            output.see('end')
            output.config(state='disabled')
        except Exception as e:
            output.config(state='normal')
            output.insert('end', f"Connection error: {e}\n")
            output.see('end')
            output.config(state='disabled')

    def send_tcp():
        try:
            if client_socket:
                client_socket.sendall(msg_entry.get().encode())
        except Exception as e:
            output.config(state='normal')
            output.insert('end', f"Send error: {e}\n")
            output.see('end')
            output.config(state='disabled')

    def close_tcp():
        stop_event.set()
        if client_socket:
            try:
                close_str = close_entry.get().strip()
                if close_str:
                    try:
                        close_bytes = bytes.fromhex(close_str)
                    except ValueError:
                        close_bytes = close_str.encode()
                    client_socket.sendall(close_bytes)
                    output.config(state='normal')
                    output.insert('end', "Connection closed.\n")
                    output.see('end')
                    output.config(state='disabled')
            except Exception as e:
                output.config(state='normal')
                output.insert('end', f"Close error: {e}\n")
                output.see('end')
                output.config(state='disabled')

    ttk.Button(win, text="Connect", command=connect_tcp).grid(row=4, column=0, pady=5)
    ttk.Button(win, text="Send", command=send_tcp).grid(row=4, column=1, pady=5)
    ttk.Button(win, text="Close", command=close_tcp).grid(row=4, column=2, pady=5)

def open_udp_client():
    win = tk.Toplevel()
    win.title("UDP Client")
    ttk.Label(win, text="IP:").grid(row=0, column=0, sticky='w', padx=(10, 0))
    ip_entry = ttk.Entry(win, width=12)
    ip_entry.insert(0, "127.0.0.1")
    ip_entry.grid(row=0, column=1, sticky='w')

    ttk.Label(win, text="Port:").grid(row=1, column=0, sticky='w', padx=(10, 0))
    port_entry = ttk.Entry(win, width=8)
    port_entry.insert(0, "1234")
    port_entry.grid(row=1, column=1, sticky='w')

    ttk.Label(win, text="Message:").grid(row=2, column=0, sticky='w', padx=(10, 0))
    msg_entry = ttk.Entry(win, width=40)
    msg_entry.grid(row=2, column=1, sticky='w')

    output = scrolledtext.ScrolledText(win, height=6, state='disabled')
    output.grid(row=3, column=0, columnspan=4, pady=5, sticky='nsew')

    def send_udp():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(msg_entry.get().encode(), (ip_entry.get(), int(port_entry.get())))
                output.config(state='normal')
                output.insert('end', "Message sent via UDP\\n")
                output.see('end')
                output.config(state='disabled')
        except Exception as e:
            output.config(state='normal')
            output.insert('end', f"Error: {e}\\n")
            output.see('end')
            output.config(state='disabled')

    ttk.Button(win, text="Send", command=send_udp).grid(row=2, column=2, columnspan=2, pady=5)

def launch_gui():
    global tcp_widgets, udp_widgets, serial_widgets
    root = ttk.Window()
    root.title("TCP/UDP Server GUI")
    root.geometry("900x700")

    top_frame = ttk.Frame(root, padding=10)
    top_frame.pack(fill='x')

    ttk.Label(top_frame, text="Server Control Panel", font=('Helvetica', 16, "bold")).pack(side='left')

    main_frame = ttk.Frame(root)
    main_frame.pack(fill='both', expand=True)
    main_frame.rowconfigure(0, weight=1)
    main_frame.columnconfigure(0, weight=1)

    tcp_frame, tcp_widgets = create_server_frame(main_frame, "TCP Server", "tcp_log.txt", service_type="tcp")
    tcp_frame.grid(row=0, column=0, sticky='nsew', padx=10, pady=5)

    udp_frame, udp_widgets = create_server_frame(main_frame, "UDP Server", "udp_log.txt", service_type="udp")
    udp_frame.grid(row=1, column=0, sticky='nsew', padx=10, pady=5)

    serial_frame, serial_widgets = create_server_frame(main_frame, "Serial Server", "serial_log.txt", service_type="serial")
    serial_frame.grid(row=2, column=0, sticky='nsew', padx=10, pady=5)

    frame_refs = {
        "tcp": tcp_frame,
        "udp": udp_frame,
        "serial": serial_frame
    }

    def save_config():
        config = read_config(config_path)

        config["tcp"] = {
                "interface": tcp_widgets["interface"].get(),
                "port": tcp_widgets["port"].get(),
                "timeout": tcp_widgets["timeout"].get() if tcp_widgets["timeout"] else "",
                "max_conn": tcp_widgets["max_conn"].get() if tcp_widgets["max_conn"] else "",
                "file": tcp_widgets["file_entry"].get()
        }

        config["udp"] ={
                "interface": udp_widgets["interface"].get(),
                "port": udp_widgets["port"].get(),
                "file": udp_widgets["file_entry"].get()
        }

        config["serial"] = {
                "interface": serial_widgets["interface"].get(),
                "baud": serial_widgets["baud"].get(),
                "parity": serial_widgets["parity"].get(),
                "databits": serial_widgets["databits"].get(),
                "stopbits": serial_widgets["stopbits"].get(),
                "file": serial_widgets["file_entry"].get()
        }

        write_config(config_path, config)
        messagebox.showinfo("Settings Saved", "Configuration saved successfully.")

    def load_config():
        try:
            path = filedialog.askopenfilename(
                title="Select Configuration File",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )
            if not path:
                return

            config = read_config(path)

            tcp = config.get("tcp", {})
            udp = config.get("udp", {})
            serial = config.get("serial", {})
            layout_conf = config.get("layout")

            tcp_widgets["interface"].set(tcp.get("interface", "0.0.0.0"))
            tcp_widgets["port"].delete(0, 'end')
            tcp_widgets["port"].insert(0, tcp.get("port", "1234"))
            if tcp_widgets["timeout"]:
                tcp_widgets["timeout"].delete(0, 'end');
                tcp_widgets["timeout"].insert(0, tcp.get("timeout", "20"))
            if tcp_widgets["max_conn"]:
                tcp_widgets["max_conn"].delete(0, 'end');
                tcp_widgets["max_conn"].insert(0, tcp.get("max_conn", "1"))
            tcp_widgets["file_entry"].delete(0, 'end')
            tcp_widgets["file_entry"].insert(0, tcp.get("file", os.path.join(script_dir, "tcp_log.txt")))

            udp_widgets["interface"].set(udp.get("interface", "0.0.0.0"))
            udp_widgets["port"].delete(0, 'end')
            udp_widgets["port"].insert(0, udp.get("port", "1234"))
            udp_widgets["file_entry"].delete(0, 'end')
            udp_widgets["file_entry"].insert(0, udp.get("file", os.path.join(script_dir, "udp_log.txt")))

            serial_widgets["interface"].set(serial.get("interface", ""))
            serial_widgets["baud"].delete(0, 'end')
            serial_widgets["baud"].insert(0, serial.get("baud", "9600"))
            serial_widgets["parity"].delete(0, 'end')
            serial_widgets["parity"].insert(0, serial.get("parity", "None"))
            serial_widgets["databits"].delete(0, 'end')
            serial_widgets["databits"].insert(0, serial.get("databits", "8"))
            serial_widgets["stopbits"].delete(0, 'end')
            serial_widgets["stopbits"].insert(0, serial.get("stopbits", "1"))
            serial_widgets["file_entry"].delete(0, 'end')
            serial_widgets["file_entry"].insert(0, serial.get("file", os.path.join(script_dir, "serial_log.txt")))

            if layout_conf:
                apply_layout(main_frame, frame_refs, layout_conf)

            messagebox.showinfo("Settings Loaded", "Configuration loaded successfully.")
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load configuration: {e}")

    helpmenu = tk.Menu(root)
    def show_help_about(parent):
        messagebox.showinfo(
            "Help / About",
            "Push Server GUI\n\n"
            "TCP/UDP/Serial server tool with logging and client simulators.\n"
            "Author: D_Steblaj\n"
            "Version: 2.0\n\n"
            "For help, see documentation or contact support."
        )

    helpmenu.add_command(label="Help / About", command=lambda: show_help_about(root))
    root.config(menu=helpmenu)

    ttk.Button(top_frame, text="Save Config", command=save_config, bootstyle="info").pack(side='left', padx=5)
    ttk.Button(top_frame, text="Load Config", command=load_config, bootstyle="info").pack(side='left', padx=5)
    ttk.Button(top_frame, text="Layout", command=lambda: open_layout_config_window(root, main_frame, frame_refs), bootstyle="secondary").pack(side='left', padx=5)
    ttk.Button(top_frame, text="TCP Client", command=open_tcp_client, bootstyle="warning").pack(side='left', padx=5)
    ttk.Button(top_frame, text="UDP Client", command=open_udp_client, bootstyle="warning").pack(side='left', padx=5)

    clock_label = ttk.Label(top_frame, font=('Helvetica', 12, 'bold'))
    clock_label.pack(side='right', padx=10)
    def update_clock():
        now = datetime.now().strftime('%H:%M:%S')
        clock_label.config(text=now)
        clock_label.after(1000, update_clock)
    update_clock()
    
    def graceful_shutdown():
        global tcp_widgets, udp_widgets, serial_widgets
        for widgets in [tcp_widgets, udp_widgets, serial_widgets]:
            try:
                if "switch" in widgets and widgets["switch"].instate(['selected']):
                    widgets["switch"].state(['!selected'])
            except Exception:
                pass

    def on_closing():
        #save_config()
        graceful_shutdown()
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
if __name__ == "__main__":
    launch_gui()