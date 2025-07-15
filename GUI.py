import os
import json
import select
import socket
import threading
from datetime import datetime
import time
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from queue import Queue


# === Global Config ===

script_dir = os.path.dirname(os.path.abspath(__file__))
default_config_path = os.path.join(script_dir, "server_config.json")
layout_config_path = os.path.join(script_dir, "layout_config.json")

tcp_setup = {
    "interface": "0.0.0.0",
    "port": 1234,
    "timeout": 20,
    "max_conn": 1,
    "close_hex": "61 62 63 0D 0A",
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
# === ============= ===


# === Utility Functions ===

def get_local_ips():
    ips = ["0.0.0.0"]
    try:
        hostname = socket.gethostname()
        ips.append(socket.gethostbyname(hostname))
    except:
        pass
    return list(set(ips))

def is_valid_hex_string(s):
    try:
        bytes.fromhex(s.replace(" ", ""))
        return True
    except ValueError:
        return False

def unified_log(message, log_file=None, gui_callback=None):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_message = f"{timestamp} {message}"
    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(full_message + "\n")
    if gui_callback:
        gui_callback(full_message)

# === ================= ===

# === Server Classes ===

class SerialServerThread(threading.Thread):
    def __init__(self, port, baudrate, bytesize, parity, stopbits, log_file, log_callback):
        super().__init__(daemon=True)
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.log_file = log_file
        self.log_callback = log_callback
        self._running = threading.Event()
        self._running.set()

    def run(self):
        try:
            import serial
            with serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.bytesize,
                parity=self.parity,
                stopbits=self.stopbits,
                timeout=1
            ) as ser:
                unified_log(f"Serial port {self.port} opened at {self.baudrate} baud", log_file=self.log_file, gui_callback=self.log_callback)
                while self._running.is_set():
                    if ser.in_waiting:
                        try:
                            line = ser.readline().decode(errors='ignore').strip()
                            unified_log(f"{self.port} {line}", log_file=self.log_file, gui_callback=self.log_callback)
                        except Exception as e:
                            unified_log(f"{self.port} Error reading data: {e}", log_file=self.log_file, gui_callback=self.log_callback)
                            break
                    time.sleep(0.1)
        except Exception as e:
            unified_log(f"Error opening serial port {self.port}: {e}", log_file=self.log_file, gui_callback=self.log_callback)

    def stop(self):
        self._running.clear()

class TCPServerThread(threading.Thread):
    def __init__(self, interface, port, timeout, max_connections, trigger_bytes, log_file, log_callback, test_mode=False):
        super().__init__(daemon=True)
        self.interface = interface
        self.port = port
        self.timeout = timeout
        self.max_connections = max_connections
        self.trigger_bytes = trigger_bytes
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

            if self.log_callback:
                unified_log(f"Listening on {self.interface}:{self.port}, timeout: {self.timeout}s, max. connections: {self.max_connections}", log_file=self.log_file, gui_callback=self.log_callback)

            while self._running.is_set():
                try:
                    conn, addr = s.accept()
                    if self.log_callback:
                        unified_log(f"{addr[0]} Connected", log_file=self.log_file, gui_callback=self.log_callback)

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
                                    unified_log(f"{addr[0]} {hex_data}", log_file=self.log_file, gui_callback=self.log_callback)

                                    if self.test_mode and total_bytes > 10:
                                        unified_log(f"{addr[0]} Test mode: Closing connection after 10 bytes", log_file=self.log_file, gui_callback=self.log_callback)
                                        break

                                    if self.trigger_bytes in data:
                                        unified_log(f"{addr[0]} Disconnected (trigger matched)", log_file=self.log_file, gui_callback=self.log_callback)
                                        break

                                except Exception as e:
                                    unified_log(f"{addr[0]} Error receiving data: {e}", log_file=self.log_file, gui_callback=self.log_callback)
                                    break
                            else:
                                unified_log(f"{addr[0]} Disconnected (timed out)", log_file=self.log_file, gui_callback=self.log_callback)
                                break

                except socket.timeout:
                    continue
                except Exception as e:
                    unified_log(f"Error: {e}", log_file=self.log_file, gui_callback=self.log_callback)

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
            if self.log_callback:
                unified_log(f"Listening on {self.interface}:{self.port}", log_file=self.log_file, gui_callback=self.log_callback)
            while self._running.is_set():
                try:
                    data, addr = s.recvfrom(1024)
                    hex_data = ' '.join(f'{b:02X}' for b in data)
                    unified_log(f"{addr[0]} {hex_data}", log_file=self.log_file, gui_callback=self.log_callback)
                    continue
                except Exception as e:
                    if self.log_callback:
                        unified_log(f"Error: {e}", log_file=self.log_file, gui_callback=self.log_callback)

    def stop(self):
        self._running.clear()

# === ============== ===


# === GUI Functions ===


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

    server_thread = None
    stop_event = threading.Event()

    def list_serial_ports():
        return [port.device for port in serial.tools.list_ports.comports()]

    def refresh_ports():
        ports = list_serial_ports()
        interface_combo['values'] = ports
        if ports:
            interface_combo.set(ports[0])

    def log_callback(msg):
        text_widget.config(state='normal')

        # Apply tag based on content
        lower_msg = msg.lower()
        if "error" in lower_msg or "fail" in lower_msg:
            tag = "error"
        elif "[partial]" in lower_msg:
            tag = "partial"
        elif "listening" in lower_msg:
            tag = "status"
        else:
            tag = "normal"

        total_lines = int(text_widget.index("end-1c").split('.')[0])
        last_visible = int(text_widget.index(f"@0,{text_widget.winfo_height()}").split('.')[0])
        at_bottom = (total_lines - last_visible) <= 2

        text_widget.insert('end', msg + '\n', tag)
        if at_bottom:
            text_widget.see('end')
        text_widget.config(state='disabled')

    serial_thread = None
    serial_obj = None
    serial_queue = Queue()

    def poll_serial_queue():
        while not serial_queue.empty():
            line = serial_queue.get()
            unified_log(line, log_file=file_entry.get(), gui_callback=log_callback)
        text_widget.after(100, poll_serial_queue)

    def read_serial_data_q(ser):
        buffer = b""
        flush_timer = time.time()

        baud = ser.baudrate
        bytes_per_sec = baud / 10.0

        while not stop_event.is_set():
            try:
                if not ser.is_open:
                    break

                chunk = ser.read(ser.in_waiting or 1)
                if chunk:
                    buffer += chunk
                    flush_timer = time.time()

                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        try:
                            decoded = line.decode(errors='ignore').strip('\r')
                            if decoded:
                                serial_queue.put(f"{ser.port} {decoded}")
                        except UnicodeDecodeError:
                            continue
                
                estimated_flush_timeout = max(0.1, min(1.5, (len(buffer) + 1) / bytes_per_sec * 3))
                idle = time.time() - flush_timer

                if idle > estimated_flush_timeout and buffer:
                    try:
                        decoded = buffer.decode(errors='ignore').rstrip('\r\n')
                        if decoded:
                            serial_queue.put(f"{ser.port} [partial] {decoded}")
                        buffer = b""
                    except:
                        buffer = b""    
            except Exception as e:
                serial_queue.put(f"{ser.port} read error: {e}")
                break

            time.sleep(0.01)
        try:
            ser.close()
        except:
            pass


    def toggle_server():
        nonlocal server_thread, serial_thread, serial_obj
        if switch.instate(['selected']):
            if service_type == "serial":
                try:
                    port = interface_combo.get()
                    baud = int(baud_combo.get())
                    parity_map = {
                        "None": serial.PARITY_NONE,
                        "Even": serial.PARITY_EVEN,
                        "Odd": serial.PARITY_ODD,
                        "Mark": serial.PARITY_MARK,
                        "Space": serial.PARITY_SPACE
                    }
                    parity = parity_map[parity_combo.get()]
                    databits = int(databits_combo.get())
                    stopbits_map = {
                        "1": serial.STOPBITS_ONE,
                        "1.5": serial.STOPBITS_ONE_POINT_FIVE,
                        "2": serial.STOPBITS_TWO
                    }
                    stopbits = stopbits_map[stopbits_combo.get()]
                    log_file = file_entry.get()

                    serial_obj = serial.Serial(port, baudrate=baud, bytesize=databits,
                                               parity=parity, stopbits=stopbits, timeout=1)
                    stop_event.clear()
                    serial_thread = threading.Thread(target=read_serial_data_q, args=(serial_obj,), daemon=True)
                    serial_thread.start()
                    poll_serial_queue()
                    unified_log(f"Serial listening on {port} @ {baud}", log_file=log_file, gui_callback=log_callback)
                    status_label.config(text="🟢 Running", foreground='green')
                except Exception as e:
                    messagebox.showerror("Serial Error", str(e))
                    unified_log(f"Error: {e}", log_file=file_entry.get(), gui_callback=log_callback)
                    switch.state(['!selected'])
            else:
                try:
                    port = int(port_spinbox.get())
                    interface = interface_combo.get()
                    output_file = file_entry.get()

                    if service_type == "tcp":
                        close_hex = close_entry.get()
                        timeout = int(timeout_entry.get())
                        max_conn = int(max_conn_entry.get())
                        trigger_bytes = bytes.fromhex(close_hex)
                        server_thread = TCPServerThread(interface, port, timeout, max_conn, trigger_bytes, output_file, log_callback, test_mode.get())
                    else:
                        server_thread = UDPServerThread(interface, port, output_file, log_callback)

                    server_thread.start()
                    status_label.config(text="🟢 Running", foreground='green')
                except Exception as e:
                    messagebox.showerror("Server Error", str(e))
                    switch.state(['!selected'])
        else:
            stop_event.set()
            if serial_thread and serial_thread.is_alive():
                serial_thread.join(timeout=2)
            if serial_obj and serial_obj.is_open:
                try:
                    serial_obj.close()
                except:
                    pass
            serial_thread = None
            serial_obj = None
            server_thread = None  # For TCP/UDP
            status_label.config(text="🔴 Stopped", foreground='red')

    switch = ttk.Checkbutton(header_frame, bootstyle="success-round-toggle", command=toggle_server)
    switch.grid(row=0, column=1, padx=(10, 5), ipadx=10, ipady=5)

    if service_type == "serial":
        ttk.Label(input_frame, text="Interface:").grid(row=0, column=0, sticky='w')
        interface_combo = ttk.Combobox(input_frame, values=[], width=10)
        interface_combo.grid(row=0, column=1, sticky='w')
        refresh_ports()

        ttk.Button(input_frame, text="↻", width=3, command=refresh_ports).grid(row=0, column=2, padx=(5, 10))

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
            ttk.Label(input_frame, text="Close Hex:").grid(row=0, column=4, sticky='w', padx=(10, 0))
            close_entry = ttk.Entry(input_frame, width=15)
            close_entry.insert(0, "61 62 63 0D 0A")
            close_entry.grid(row=0, column=5, sticky='w')

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
        "close_hex": close_entry if service_type == "tcp" else None,
        "timeout": timeout_entry if service_type == "tcp" else None,
        "max_conn": max_conn_entry if service_type == "tcp" else None,
        "file_entry": file_entry,
        "text_widget": text_widget,
        "status_label": status_label,
        "switch": switch
    }

    
# === ============= ===

# === Layout Configuration ===

def open_layout_config_window(root, main_frame, frame_refs):
    def save_and_apply():
        config = {
            "visible": {k: var.get() for k, var in visibility_vars.items()},
            "layout": layout_var.get()
        }
        with open(layout_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        apply_layout(main_frame, frame_refs, config)
        win.destroy()

    win = tk.Toplevel(root)
    win.title("Layout Configuration")

    # Load existing config if available
    try:
        with open(layout_config_path, "r", encoding="utf-8") as f:
            existing_config = json.load(f)
    except Exception:
        existing_config = {"visible": {}, "layout": "vertical"}

    visibility_vars = {}
    for i, name in enumerate(frame_refs):
        default_visible = existing_config.get("visible", {}).get(name, True)
        visibility_vars[name] = tk.BooleanVar(value=default_visible)
        ttk.Checkbutton(win, text=f"Show {name.upper()}", variable=visibility_vars[name]).grid(row=i, column=0, sticky="w")

    ttk.Label(win, text="Layout Style:").grid(row=0, column=2, padx=10)
    layout_var = tk.StringVar(value=existing_config.get("layout", "vertical"))
    layout_options = ["vertical", "horizontal"]
    layout_menu = ttk.OptionMenu(win, layout_var, layout_var.get(), *layout_options)
    layout_menu.grid(row=0, column=3, padx=10)

    ttk.Button(win, text="Apply", command=save_and_apply).grid(row=len(frame_refs)+1, column=0, columnspan=4, pady=10)

def apply_layout(main_frame, frame_refs, config):
    for widget in main_frame.winfo_children():
        widget.grid_forget()

    layout = config.get("layout", "vertical")
    visible = config.get("visible", {})

    # Reset all grid configuration
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

# === Client Simulators ===

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

# === Main GUI Launcher ===

def launch_gui():
    global tcp_widgets, udp_widgets
    root = ttk.Window(themename="darkly")
    root.title("TCP/UDP Server GUI")
    root.geometry("900x700")

    top_frame = ttk.Frame(root, padding=10)
    top_frame.pack(fill='x')

    ttk.Label(top_frame, text="Server Control Panel", font=('Helvetica', 16, "bold")).pack(side='left')

    main_frame = ttk.Frame(root)
    main_frame.pack(fill='both', expand=True)
    main_frame.rowconfigure(0, weight=1)
    main_frame.columnconfigure(0, weight=1)

    def update_text_widget_theme():
        theme_name = root.style.theme.name
        text_color = "white" if theme_name in ["darkly", "superhero", "cyborg", "solar", "vapor"] else "black"
        for widget_dict in [tcp_widgets, udp_widgets, serial_widgets]:
            widget_dict["text_widget"].tag_config("normal", foreground=text_color)

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

    def toggle_theme():
        current = root.style.theme.name
        new_theme = "darkly" if current == "flatly" else "flatly"
        root.style.theme_use(new_theme)
        update_text_widget_theme()

    def save_config():
        config = {
            "tcp": {
                "interface": tcp_widgets["interface"].get(),
                "port": tcp_widgets["port"].get(),
                "close_hex": tcp_widgets["close_hex"].get(),
                "timeout": tcp_widgets["timeout"].get() if tcp_widgets["timeout"] else "",
                "max_conn": tcp_widgets["max_conn"].get() if tcp_widgets["max_conn"] else "",
                "file": tcp_widgets["file_entry"].get()
            },
            "udp": {
                "interface": udp_widgets["interface"].get(),
                "port": udp_widgets["port"].get(),
                "file": udp_widgets["file_entry"].get()
            },
            "serial": {
                "interface": serial_widgets["interface"].get(),
                "baud": serial_widgets["baud"].get(),
                "parity": serial_widgets["parity"].get(),
                "databits": serial_widgets["databits"].get(),
                "stopbits": serial_widgets["stopbits"].get(),
                "file": serial_widgets["file_entry"].get()
            },
            "theme": root.style.theme.name
        }

        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialdir=script_dir,
            initialfile="Push_Server_conf.json",
            filetypes=[("JSON files", "*.json")]
        )
        if path:
            with open(path, "w") as f:
                json.dump(config, f, indent=2)
            messagebox.showinfo("Settings Saved", "Configuration saved successfully.")

    def load_config():
        try:
            path = filedialog.askopenfilename(
                title="Select Configuration File",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )
            if not path:
                return

            with open(path, "r") as f:
                config = json.load(f)

            tcp = config.get("tcp", {})
            udp = config.get("udp", {})
            serial = config.get("serial", {})

            tcp_widgets["interface"].set(tcp.get("interface", "0.0.0.0"))
            tcp_widgets["port"].delete(0, 'end')
            tcp_widgets["port"].insert(0, tcp.get("port", "1234"))
            tcp_widgets["close_hex"].delete(0, 'end')
            tcp_widgets["close_hex"].insert(0, tcp.get("close_hex", ""))
            tcp_widgets["timeout"].delete(0, 'end')
            tcp_widgets["timeout"].insert(0, tcp.get("timeout", ""))
            tcp_widgets["max_conn"].delete(0, 'end')
            tcp_widgets["max_conn"].insert(0, tcp.get("max_conn", ""))
            tcp_widgets["file_entry"].delete(0, 'end')
            tcp_widgets["file_entry"].insert(0, tcp.get("file", ""))

            udp_widgets["interface"].set(udp.get("interface", "0.0.0.0"))
            udp_widgets["port"].delete(0, 'end')
            udp_widgets["port"].insert(0, udp.get("port", "1234"))
            udp_widgets["file_entry"].delete(0, 'end')
            udp_widgets["file_entry"].insert(0, udp.get("file", ""))

            serial_widgets["interface"].set(serial.get("interface", ""))
            serial_widgets["baud"].delete(0, 'end')
            serial_widgets["baud"].insert(0, serial.get("baud", "9600"))
            serial_widgets["parity"].delete(0, 'end')
            serial_widgets["parity"].insert(0, serial.get("parity", ""))
            serial_widgets["databits"].delete(0, 'end')
            serial_widgets["databits"].insert(0, serial.get("databits", ""))
            serial_widgets["stopbits"].delete(0, 'end')
            serial_widgets["stopbits"].insert(0, serial.get("stopbits", ""))
            serial_widgets["file_entry"].delete(0, 'end')
            serial_widgets["file_entry"].insert(0, serial.get("file", ""))

            root.style.theme_use(config.get("theme", "flatly"))
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load configuration: {e}")
    
    ttk.Button(top_frame, text="Save Config", command=save_config, bootstyle="secondary").pack(side='left', padx=5)
    ttk.Button(top_frame, text="Load Config", command=load_config, bootstyle="secondary").pack(side='left', padx=5)
    ttk.Button(top_frame, text="Layout Config", command=lambda: open_layout_config_window(root, main_frame, frame_refs)).pack(side='left', padx=5)
    ttk.Button(top_frame, text="Toggle Theme", command=toggle_theme, bootstyle="secondary").pack(side='right', padx=5)
    ttk.Button(top_frame, text="UDP Client", command=open_udp_client, bootstyle="info").pack(side='right', padx=5)
    ttk.Button(top_frame, text="TCP Client", command=open_tcp_client, bootstyle="info").pack(side='right', padx=5)

    def on_closing():
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

# === ================= ===

# === Entry Point ===

if __name__ == "__main__":
    launch_gui()

# === =========== ===