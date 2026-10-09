import sys
import subprocess
import os

def ensure_dependencies():
    """Checks for required dependencies and asks user permission before auto-installing."""
    required = ["pyserial"]
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
        print(f"[!] Missing required package: {', '.join(missing)}")
        choice = input("[?] Do you want to proceed with downloading dependencies? (y/n): ").strip().lower()
        if choice in ['y', 'yes']:
            print("[+] Installing missing dependencies...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
                print("[+] Dependency successfully installed!\r\n")
            except Exception as e:
                print(f"[-] Auto-installation failed: {e}")
                sys.exit(1)
        else:
            print("[!] Cannot continue without required dependencies. Exiting.")
            sys.exit(0)

ensure_dependencies()

import time
import serial
import serial.tools.list_ports
import re
import tempfile

if os.name == 'nt':
    import msvcrt
else:
    import select
    import tty
    import termios

BAUD_RATE = 9600
NEW_ROOT_PASSWORD = "juniper123"

# --- Telemetry Helpers for Main Dashboard ---
def report_status(status_code: str):
    """
    Emits telemetry tags to stdout for the Manager dashboard.
    status_code options: IN_PROGRESS (Green), PAUSED_MANUAL (Grey), ERROR (Red), COMPLETE (Blue/Green)
    """
    sys.stdout.write(f"\r\n[STATUS:{status_code}]\r\n")
    sys.stdout.flush()

def report_progress(percent: int):
    """Emits progress percentage tags."""
    sys.stdout.write(f"\r\n[PROGRESS:{percent}]\r\n")
    sys.stdout.flush()

JUNIPER_CLI = [
    (r"root.*>", "configure"),
    ("#", "request system zeroize"),
    ("[yes/no]:", "yes")
]

CISCO_CLI = [
    ("switch:", "rename flash:config.text flash:config.old"),
    ("switch:", "boot")
]

CISCO_CONFREG = [
    (r"do you wish to change the configuration\? y/n", "y"),
    (r"enable  \"diagnostic mode\"\?", "n"),
    (r"enable  \"use net in IP bcast address\"\?", "n"),
    (r"disable \"load rom after netboot fails\"\?", "n"),
    (r"enable  \"use all zero broadcast\"\?", "n"),
    (r"enable  \"ignore system config info\"\?", "y"),
    (r"change console baud rate\?", "n"),
    (r"change the boot characteristics\?", "n"),
    (r"do you wish to save this configuration\?", "y"),
    ("rommon 2>", "reset")
]

JUNIPER_ROOT = [
    (r"root@:RE:0%", "cli"),
    (r"root>", "show chassis hardware")
]

CISCO_ROOT = [
    (r"Switch#", "conf t"),
    (r"Switch", "do show version | include number")
]

def copy_to_clipboard(text: str):
    try:
        if os.name == 'nt':
            subprocess.run(['clip'], input=text.strip(), text=True, check=True)
        elif sys.platform == 'darwin':
            subprocess.run(['pbcopy'], input=text.strip(), text=True, check=True)
        else:
            subprocess.run(['xclip', '-selection', 'clipboard'], input=text.strip(), text=True, check=True)
    except Exception:
        pass

def strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def normalize_text(text: str) -> str:
    cleaned = strip_ansi(text)
    return re.sub(r'\s+', ' ', cleaned)

def check_keyboard_input():
    if os.name == 'nt':
        if msvcrt.kbhit():
            try:
                ch = msvcrt.getch()
                return ch.decode('utf-8', errors='ignore')
            except Exception:
                return None
    else:
        rlist, _, _ = select.select([sys.stdin], [], [], 0.0)
        if rlist:
            return sys.stdin.read(1)
    return None

def run_interactive_screen(ser):
    report_status("PAUSED_MANUAL")  # Turns progress bar GREY on main terminal
    print("\r\n" + "="*60)
    print(" LIVE CONSOLE CONNECTION ACTIVE ")
    print(" -> Type commands directly to the hardware device below.")
    print(" -> Press [ Ctrl+S ] at any time to resume automated execution script.")
    print(" -> Press [ Ctrl+K ] at any time to kill the process.")
    print("="*60 + "\r\n")
    
    try:
        while True:
            if ser.in_waiting > 0:
                chunk = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                formatted_chunk = chunk.replace('\n', '\r\n')
                sys.stdout.write(formatted_chunk)
                sys.stdout.flush()

            local_key = check_keyboard_input()
            if local_key:
                if local_key == '\x0b':  # Ctrl + K
                    print("\r\n[!] Program execution killed cleanly via Ctrl+K.\r")
                    report_status("ERROR")
                    sys.exit(0)
                elif local_key == '\x13':  # Ctrl + S
                    print("\r\n[+] Resuming background automation script routine...\r\n")
                    report_status("IN_PROGRESS")  # Turns progress bar back GREEN
                    return

                ser.write(local_key.encode('utf-8', errors='ignore'))
            time.sleep(0.01)

    except (serial.SerialException, OSError):
        report_status("ERROR")
        print("\r\n[!] Connection dropped: USB serial cable pulled.\r")

def send_when(ser, commands_list: list[tuple[str, str]], timeout=120, delay=0.5):
    commands = list(commands_list)
    buffer = ""
    end_time = time.time() + timeout
    time.sleep(delay)    

    while time.time() < end_time:
        if not commands:
            return True
        
        key = check_keyboard_input()
        if key == '\x0b':  # Ctrl+K
            report_status("ERROR")
            sys.exit(0)

        if key == '\x13': # Ctrl-S
            run_interactive_screen(ser)
            end_time = time.time() + timeout
        
        if ser.in_waiting > 0:
            chunk = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
            cleaned_chunk = strip_ansi(chunk)
            
            formatted_chunk = cleaned_chunk.replace('\n', '\r\n')
            sys.stdout.write(formatted_chunk)
            sys.stdout.flush()
            
            buffer += cleaned_chunk
            expected, command = commands[0]

            if "-- MORE --" in buffer:
                ser.write(b" ")
                buffer = ""
            elif re.search(expected, buffer):
                print(f"\r\n[>>> Matched '{expected}' -> Sending: {command}]\r")
                ser.write((command + "\n").encode())
                del commands[0]
                buffer = ""
                end_time = time.time() + timeout
        time.sleep(0.01)
    return False

def main():
    if len(sys.argv) < 2:
        print("[-] Error: Port argument required for execution.\r\n")
        report_status("ERROR")
        sys.exit(1)
        
    port_name = sys.argv[1]
    
    try:
        ser = serial.Serial(port_name, BAUD_RATE, timeout=1)
    except Exception as e:
        print(f"[-] Error: Failed to open interface connection: {e}\r\n")
        report_status("ERROR")
        sys.exit(1)

    report_status("IN_PROGRESS")  # Initial state: Green progress bar
    report_progress(10)
    print(f"[+] Connected to {port_name}. Listening for switch activity...")

    break_sequence = True
    buffer = ""
    boottype = ""
    autoboot = True
    in_recovery = False
    isreset = False
    islocked = False

    pressed_5 = False
    pressed_2 = False

    last_break_time = 0.0
    break_pulse_interval = 1.0

    old_settings = None
    if os.name != 'nt':
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        new_settings = termios.tcgetattr(fd)
        new_settings[3] = new_settings[3] & ~termios.ICANON & ~termios.ECHO & ~termios.ISIG
        new_settings[0] = new_settings[0] & ~termios.IXON
        termios.tcsetattr(fd, termios.TCSANOW, new_settings)

    try:
        while True:
            key = check_keyboard_input()
            if key == '\x0b':  # Ctrl + K
                report_status("ERROR")
                break
                
            if key == '\x13' or isreset: # Ctrl + S
                if not isreset:
                    run_interactive_screen(ser)
                    break_sequence = True
                else:
                    print("\r\n[✓] Device reset confirmed true. Spawning Terminal Console...\r")
                    run_interactive_screen(ser)
                    
                    break_sequence = True
                    buffer = ""
                    boottype = ""
                    autoboot = True
                    in_recovery = False
                    isreset = False
                    islocked = False
                    
                    pressed_5 = False
                    pressed_2 = False

            try:
                has_data = ser.in_waiting > 0
            except (serial.SerialException, OSError):
                report_status("ERROR")
                print("\r\n[!] CRITICAL: USB Serial Interface Adapter disconnected!\r")
                break

            if has_data:
                break_sequence = False
                chunk = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                
                formatted_chunk = chunk.replace('\n', '\r\n')
                sys.stdout.write(formatted_chunk)
                sys.stdout.flush()
                                
                cleaned_chunk = strip_ansi(chunk)
                buffer += cleaned_chunk
                search_buffer = normalize_text(buffer)

                if "login:" in buffer.lower() and not islocked:
                    time.sleep(1)
                    ser.write(b"root\n")
                    buffer = ""

                elif "password:" in buffer.lower():
                    time.sleep(1)
                    ser.write(b"\n")
                    buffer = ""

                elif "Login incorrect" in buffer:
                    buffer = ""
                    islocked = True
                    report_status("ERROR")  # Locked switch config -> Red bar
                    print("\r\n[!] Active configuration locked. Flip power switch.\r")
                    run_interactive_screen(ser)

                elif "root@:RE:0%" in buffer:
                    report_progress(50)
                    ser.write(b"\n")

                    if send_when(ser, JUNIPER_ROOT):
                        if ser.in_waiting > 0:
                            buffer += strip_ansi(ser.read(ser.in_waiting).decode('utf-8', errors='ignore'))
                            
                        chassis_match = re.search(r"Chassis\s+([A-Za-z0-9\-]+)\s+([A-Za-z0-9\-]+)", buffer)
                        dev_modeltag = chassis_match.group(2) if chassis_match else "UNKNOWN MODEL"
                        dev_sertag = chassis_match.group(1) if chassis_match else "UNKNOWN SERIAL"

                        if dev_sertag != "UNKNOWN SERIAL":
                            copy_to_clipboard(dev_sertag)
                        
                        print(f"Model Tag: {dev_modeltag}")
                        print(f"Serial Tag: {dev_sertag}")
                        report_progress(100)
                        report_status("COMPLETE")
                        isreset = True
                        buffer = ""
                    else:
                        report_status("ERROR")

                elif "Press RETURN to get started!" in buffer:
                    ser.write(b"\n" * 15) 
                    buffer = ""

                elif "Switch>" in buffer:
                    report_progress(50)
                    ser.write(b"enable\n")

                    if send_when(ser, CISCO_ROOT):
                        if ser.in_waiting > 0:
                            buffer += strip_ansi(ser.read(ser.in_waiting).decode('utf-8', errors='ignore'))
                        
                        model_match = re.search(r"Model number\s*:\s*([A-Za-z0-9\-]+)", buffer)
                        dev_modeltag = model_match.group(1) if model_match else "UNKNOWN MODEL"
                        
                        serial_match = re.search(r"System serial number\s*:\s*([A-Za-z0-9\-]+)", buffer)
                        dev_sertag = serial_match.group(1) if serial_match else "UNKNOWN SERIAL"
                        
                        if dev_sertag != "UNKNOWN SERIAL":
                            copy_to_clipboard(dev_sertag)
                        
                        print(f"Model Tag: {dev_modeltag}")
                        print(f"Serial Tag: {dev_sertag}")
                        report_progress(100)
                        report_status("COMPLETE")
                        isreset = True
                        buffer = ""
                    else:
                        report_status("ERROR")

                elif "Hit [Enter] to boot immediately, or space bar for command prompt." in buffer and autoboot and not isreset:
                    report_progress(30)
                    ser.write(b" ")
                    time.sleep(1)
                    ser.write(b"boot -s\n")
                    autoboot = False
                    boottype = "juniper - yes"
                    buffer = ""

                elif re.search(r"(autoboot in|press ctrl-c)", search_buffer, re.IGNORECASE) and autoboot:
                    report_progress(35)
                    ser.write(b"\x03")
                    autoboot = False
                    buffer = ""

                elif "rommon 1 >" in buffer and not autoboot and not isreset:
                    report_progress(40)
                    ser.write(b"confreg\n")
                    if send_when(ser, CISCO_CONFREG):
                        isreset = True
                        buffer = ""

                elif re.search(r"5\.\s*\[?M\]?ore\s*options", search_buffer, re.IGNORECASE) and not pressed_5 and not isreset:
                    ser.write(b"5")
                    pressed_5 = True
                    autoboot = False
                    buffer = ""

                elif re.search(r"2\.\s*Recovery\s*mode", search_buffer, re.IGNORECASE) and pressed_5 and not pressed_2 and not isreset:
                    ser.write(b"2")
                    pressed_2 = True
                    boottype = "juniper - exit"
                    in_recovery = True
                    buffer = ""

                elif "switch:" in buffer and autoboot:
                    report_progress(40)
                    ser.write(b"flash_init\n")
                    if send_when(ser, CISCO_CLI):
                        isreset = True
                        buffer = ""

                elif "Starting CLI ..." in buffer and in_recovery:
                    report_progress(70)
                    if boottype == "juniper - yes":
                        if send_when(ser, JUNIPER_CLI):
                            ser.write(b"y\n")
                            isreset = True
                            buffer = ""
                    elif boottype == "juniper - exit":
                        if send_when(ser, JUNIPER_CLI):
                            ser.write(b"exit\n")
                            isreset = True
                            buffer = ""

                if len(buffer) > 2000:
                    buffer = buffer[-1000:]

            elif not has_data and break_sequence:
                current_time = time.time()
                if current_time - last_break_time > break_pulse_interval:
                    try:
                        ser.write(b"\r\n\n ")
                    except (serial.SerialException, OSError):
                        report_status("ERROR")
                        break
                    last_break_time = current_time
            time.sleep(0.01)

    except KeyboardInterrupt:
        report_status("ERROR")
    finally:
        if old_settings and os.name != 'nt':
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
        try:
            ser.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()