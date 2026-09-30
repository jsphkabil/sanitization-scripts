import os
import sys
import time
import queue
import threading
import subprocess
import re
import serial
import serial.tools.list_ports

# Auto-install Rich UI dependency if missing
try:
    from rich.live import Live
    from rich.table import Table
    from rich.console import Console
except ImportError:
    print("[+] Missing requirement 'rich'. Installing automatically...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich", "pyserial"])
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
        
        # State Lock Flags
        self.is_locked = False
        self.sanitization_completed = False  # Prevents infinite re-run loops on success
        
        self.stop_requested = False
        self.switch_powered_on = False
        self.process = None

    def check_switch_power(self) -> bool:
        """
        Detects if the target switch is powered on on the other side of the serial cable
        by inspecting DSR/CTS handshaking pin voltage or active RX buffer traffic.
        """
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
            # 1. Check if the port is locked following a successful completion
            if self.is_locked or self.sanitization_completed:
                self.status = "COMPLETE (LOCKED - REQUIRING USER RESET)"
                self.progress = 100
                time.sleep(1)
                continue

            # 2. Monitor host connection & Switch Power-On
            self.switch_powered_on = self.check_switch_power()

            if not self.switch_powered_on:
                self.status = "WAITING FOR SWITCH POWER"
                self.progress = 0
                time.sleep(1.5)
                continue

            # 3. Switch detected online! Launch background sanitization
            self.status = "SANITIZING IN BACKGROUND"
            self.progress = 10
            script_succeeded = False

            try:
                # Spawns sanitization-script.py <port_name> in background
                self.process = subprocess.Popen(
                    [sys.executable, script_path, self.port],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )

                # Monitor real-time telemetry output from sanitization-script.py
                for line in iter(self.process.stdout.readline, ''):
                    if self.stop_requested:
                        break
                    
                    cleaned_line = line.strip()
                    
                    # Parse status tags sent by sanitization-script.py
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

                    # Parse hardware identification tags
                    if "Model Tag:" in cleaned_line:
                        match = re.search(r"Model Tag:\s*([A-Za-z0-9\-]+)", cleaned_line)
                        if match:
                            self.model = match.group(1)
                    elif "Serial Tag:" in cleaned_line:
                        match = re.search(r"Serial Tag:\s*([A-Za-z0-9\-]+)", cleaned_line)
                        if match:
                            self.serial_num = match.group(1)

                self.process.wait()

                # Evaluate execution results
                if self.process.returncode == 0 or script_succeeded:
                    # SUCCESS: Lock port to avoid endless loops
                    self.status = "COMPLETE (LOCKED)"
                    self.progress = 100
                    self.sanitization_completed = True
                    self.is_locked = True
                else:
                    # FAILURE/DISCONNECT MID-WAY: Reset progress & prepare for auto-restart on reconnect
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
        """Cleanly terminates worker thread and child processes."""
        self.stop_requested = True
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except Exception:
                pass

    def unlock_and_reset(self):
        """User manual unlock command to clear state for a new switch on this cable."""
        self.is_locked = False
        self.sanitization_completed = False
        self.status = "WAITING FOR SWITCH POWER"
        self.progress = 0
        self.model = "N/A"
        self.serial_num = "N/A"

    def open_interactive_terminal(self):
        """Spawns an independent terminal window connected directly to this port."""
        if sys.platform == 'darwin':  # macOS
            cmd = f"osascript -e 'tell application \"Terminal\" to do script \"screen {self.port} {BAUD_RATE}\"'"
            subprocess.Popen(cmd, shell=True)
        elif os.name == 'nt':  # Windows
            cmd = f"start cmd /k mode {self.port}:{BAUD_RATE},n,8,1"
            subprocess.Popen(cmd, shell=True)
        else:  # Linux
            subprocess.Popen(["xterm", "-e", f"screen {self.port} {BAUD_RATE}"])


class MassSanitizationManager:
    def __init__(self):
        self.workers = {}
        self.console = Console()

    def discover_ports(self):
        """Finds all active FTDI, Prolific, or USB-to-Serial adapters connected to host."""
        matched_ports = []
        for port in serial.tools.list_ports.comports():
            desc = (port.description or "").lower()
            mfg = (port.manufacturer or "").lower()
            if any(chip in desc or chip in mfg for chip in ["ftdi", "prolific", "cp210", "ch340", "usb serial", "usb-to-serial", "tty.usb"]):
                matched_ports.append(port.device)
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
            # Dynamic bar coloring based on status state
            color = "green"
            if "PAUSED" in worker.status or "MANUAL" in worker.status:
                color = "grey50"  # Grey on manual interactive override (Ctrl+S)
            elif "ERROR" in worker.status or "FAILED" in worker.status:
                color = "red"     # Red on failures or lockouts
            elif "COMPLETE" in worker.status:
                color = "cyan"    # Cyan on complete state

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

                    # 1. Clean up unplugged host ports (unplugged host cables unlock and reset on reconnect)
                    for existing_port in list(self.workers.keys()):
                        if existing_port not in current_ports:
                            self.workers[existing_port].stop()
                            del self.workers[existing_port]

                    # 2. Add newly plugged host serial ports
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