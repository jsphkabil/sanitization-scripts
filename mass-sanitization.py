import os
import sys
import subprocess

def ensure_dependencies():
    """Checks for required dependencies and asks user permission before auto-installing."""
    required = ["rich", "pyserial"]
    missing = []
    
    for pkg in required:
        try:
            if pkg == "pyserial":
                import serial
            else:
                __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"[!] The following required packages are missing: {', '.join(missing)}")
        choice = input("[?] Do you want to proceed with downloading dependencies? (y/n): ").strip().lower()
        if choice in ['y', 'yes']:
            print("[+] Installing missing dependencies...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
                print("[+] Dependencies successfully installed!\n")
            except Exception as e:
                print(f"[-] Installation failed: {e}")
                sys.exit(1)
        else:
            print("[!] Cannot continue without required dependencies. Exiting.")
            sys.exit(0)

ensure_dependencies()

import time
import queue
import threading
import re
import serial
import serial.tools.list_ports
from rich.live import Live
from rich.table import Table
from rich.console import Console

BAUD_RATE = 9600
WORKER_SCRIPT_NAME = "sanitization-script.py"


class PortWorker(threading.Thread):
    def __init__(self, port_device):
        super().__init__()
        self.port = port_device
        self.daemon = True
        
        self.status = "INITIALIZING"
        self.progress = 0
        self.model = "N/A"
        self.serial_num = "N/A"
        
        self.is_locked = False
        self.sanitization_completed = False
        self.stop_requested = False
        self.switch_powered_on = False
        self.process = None

    def check_switch_power(self) -> bool:
        try:
            ser = serial.Serial(self.port, BAUD_RATE, timeout=0.2)
            if ser.cts or ser.dsr or ser.in_waiting > 0:
                ser.close()
                return True
            ser.close()
        except Exception:
            pass
        return False

    def run(self):
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), WORKER_SCRIPT_NAME)

        while not self.stop_requested:
            if self.is_locked or self.sanitization_completed:
                self.status = "COMPLETE (LOCKED - REQUIRING USER RESET)"
                self.progress = 100
                time.sleep(1)
                continue

            self.switch_powered_on = self.check_switch_power()

            if not self.switch_powered_on:
                self.status = "WAITING FOR SWITCH POWER"
                self.progress = 0
                time.sleep(1.5)
                continue

            self.status = "SANITIZING IN BACKGROUND"
            self.progress = 10
            script_succeeded = False

            try:
                self.process = subprocess.Popen(
                    [sys.executable, script_path, self.port],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )

                for line in iter(self.process.stdout.readline, ''):
                    if self.stop_requested:
                        break
                    
                    cleaned_line = line.strip()
                    
                    if "[STATUS:IN_PROGRESS]" in cleaned_line:
                        if self.status != "RECOVERY/RESET IN PROGRESS":
                            self.status = "SANITIZING IN BACKGROUND"
                    elif "[STATUS:PAUSED_MANUAL]" in cleaned_line:
                        self.status = "PAUSED (MANUAL INTERVIEW ACTIVE)"
                    elif "[STATUS:ERROR]" in cleaned_line:
                        self.status = "ERROR / INTERRUPTED"
                    elif "[STATUS:COMPLETE]" in cleaned_line:
                        script_succeeded = True
                    elif "[PROGRESS:" in cleaned_line:
                        match = re.search(r"\[PROGRESS:(\d+)\]", cleaned_line)
                        if match:
                            self.progress = int(match.group(1))

                    if "Model Tag:" in cleaned_line:
                        match = re.search(r"Model Tag:\s*([A-Za-z0-9\-]+)", cleaned_line)
                        if match:
                            self.model = match.group(1)
                    elif "Serial Tag:" in cleaned_line:
                        match = re.search(r"Serial Tag:\s*([A-Za-z0-9\-]+)", cleaned_line)
                        if match:
                            self.serial_num = match.group(1)

                self.process.wait()

                if self.process.returncode == 0 or script_succeeded:
                    self.status = "COMPLETE (LOCKED)"
                    self.progress = 100
                    self.sanitization_completed = True
                    self.is_locked = True
                else:
                    self.status = "FAILED / REPOWER REQUIRED"
                    self.progress = 0
                    self.sanitization_completed = False
                    self.is_locked = False
                    time.sleep(2)

            except Exception as e:
                self.status = f"ERROR: {str(e)}"
                self.sanitization_completed = False
                self.is_locked = False
                time.sleep(3)

    def stop(self):
        self.stop_requested = True
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except Exception:
                pass

    def unlock_and_reset(self):
        self.is_locked = False
        self.sanitization_completed = False
        self.status = "WAITING FOR SWITCH POWER"
        self.progress = 0
        self.model = "N/A"
        self.serial_num = "N/A"

    def open_interactive_terminal(self):
        """Spawns an independent terminal window using PySerial's built-in miniterm."""
        miniterm_cmd = f'"{sys.executable}" -m serial.tools.miniterm {self.port} {BAUD_RATE}'
        
        if sys.platform == 'darwin':  # macOS
            cmd = f'osascript -e \'tell application "Terminal" to do script "{miniterm_cmd}"\''
            subprocess.Popen(cmd, shell=True)
        elif os.name == 'nt':  # Windows
            cmd = f'start cmd /k "{miniterm_cmd}"'
            subprocess.Popen(cmd, shell=True)
        else:  # Linux
            subprocess.Popen(["xterm", "-e", miniterm_cmd])


class MassSanitizationManager:
    def __init__(self):
        self.workers = {}
        self.console = Console()

    def discover_ports(self):
        matched_ports = []
        for port in serial.tools.list_ports.comports():
            device = port.device
            
            if sys.platform == 'darwin' and '/dev/tty.' in device:
                device = device.replace('/dev/tty.', '/dev/cu.')

            desc = (port.description or "").lower()
            mfg = (port.manufacturer or "").lower()
            dev_lower = device.lower()

            keywords = ["ftdi", "prolific", "cp210", "ch340", "usb serial", "usb-to-serial", "usbserial", "cu.usb"]
            if any(chip in desc or chip in mfg or chip in dev_lower for chip in keywords):
                if device not in matched_ports:
                    matched_ports.append(device)
        return matched_ports

    def generate_dashboard(self) -> Table:
        table = Table(title="[bold green]MASS SWITCH SANITIZATION MANAGER[/bold green]", expand=True)
        table.add_column("ID", style="cyan", justify="center", width=4)
        table.add_column("Serial Port", style="bold yellow", width=18)
        table.add_column("Switch Power", justify="center", width=14)
        table.add_column("Status / Stage", width=32)
        table.add_column("Model Tag", width=15)
        table.add_column("Serial Tag", width=15)
        table.add_column("Progress", width=25)

        for idx, (port, worker) in enumerate(list(self.workers.items())):
            color = "green"
            if "PAUSED" in worker.status or "MANUAL" in worker.status:
                color = "grey50"
            elif "ERROR" in worker.status or "FAILED" in worker.status:
                color = "red"
            elif "COMPLETE" in worker.status:
                color = "cyan"

            blocks = int(worker.progress / 5)
            p_bar = f"[{color}]{'█' * blocks}{'░' * (20 - blocks)} {worker.progress}%[/{color}]"
            p_status = "[bold green]ONLINE[/bold green]" if worker.switch_powered_on else "[bold red]OFF / NO SIGNAL[/bold red]"
            
            table.add_row(
                str(idx),
                port,
                p_status,
                worker.status,
                worker.model,
                worker.serial_num,
                p_bar
            )
        return table

    def run(self):
        self.console.print("[+] Starting Mass Sanitization Manager...", style="bold blue")
        
        try:
            with Live(self.generate_dashboard(), refresh_per_second=2, console=self.console) as live:
                while True:
                    current_ports = self.discover_ports()

                    for existing_port in list(self.workers.keys()):
                        if existing_port not in current_ports:
                            self.workers[existing_port].stop()
                            del self.workers[existing_port]

                    for p in current_ports:
                        if p not in self.workers:
                            worker = PortWorker(p)
                            worker.start()
                            self.workers[p] = worker

                    live.update(self.generate_dashboard())
                    time.sleep(0.5)

        except KeyboardInterrupt:
            self.console.print("\n[!] Shutting down manager...", style="bold red")
            for worker in self.workers.values():
                worker.stop()


if __name__ == "__main__":
    manager = MassSanitizationManager()
    manager.run()