import sys
import subprocess
import os

def ensure_dependencies():
    """Checks for required dependencies and auto-installs missing packages."""
    try:
        import serial
        import serial.tools.list_ports
    except ImportError:
        print("[+] Missing required dependency 'pyserial'. Auto-installing...")
        try:
            # Attempts auto-installation via pip across Windows & Mac
            python_executable = sys.executable
            subprocess.check_call([python_executable, "-m", "pip", "install", "pyserial"])
            print("[+] Dependency 'pyserial' successfully installed!\r\n")
        except Exception as e:
            print(f"[-] Auto-installation failed: {e}")
            print("[-] Please manually run: pip install pyserial\r\n")
            sys.exit(1)

ensure_dependencies()

import time
import serial
import serial.tools.list_ports
import re
import tempfile

# Cross-platform non-blocking console keyboard input setup
if os.name == 'nt':
    import msvcrt
else:
    import select
    import tty
    import termios

BAUD_RATE = 9600
NEW_ROOT_PASSWORD = "juniper123"

# JUNIPER_CLI = [
#     (r"root.*>", "configure"),
#     ("#", "load factory-default"),
#     ("#", "set system root-authentication plain-text-password"),
#     ("New password:", NEW_ROOT_PASSWORD),
#     ("Retype new password:", NEW_ROOT_PASSWORD),
#     ("#", "commit and-quit"),
#     (r"root.*>", "exit")
# ]

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
    """Copies a text string to the system clipboard across OS platforms."""
    try:
        if os.name == 'nt':  # Windows
            subprocess.run(['clip'], input=text.strip(), text=True, check=True)
        elif sys.platform == 'darwin':  # macOS
            subprocess.run(['pbcopy'], input=text.strip(), text=True, check=True)
        else:  # Linux (requires xclip)
            subprocess.run(['xclip', '-selection', 'clipboard'], input=text.strip(), text=True, check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

def strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def normalize_text(text: str) -> str:
    """Strips ANSI sequences, replaces control characters/carriage returns with standard spaces."""
    cleaned = strip_ansi(text)
    return re.sub(r'\s+', ' ', cleaned)

def get_target_ports():
    matched_ports = []
    ports = serial.tools.list_ports.comports()
    for port in ports:
        desc = (port.description or "").lower()
        manufacturer = (port.manufacturer or "").lower()
        if any(chip in desc or chip in manufacturer for chip in ["ftdi", "prolific", "cp210", "ch340", "usb serial", "usb-to-serial"]):
            matched_ports.append(port.device)
    return matched_ports

def get_lock_filepath(port_name: str) -> str:
    safe_name = "".join([c if c.isalnum() else "_" for c in port_name])
    return os.path.join(tempfile.gettempdir(), f"reset_lock_{safe_name}.lock")

def is_process_running(pid: int) -> bool:
    """Cross-platform check to see if a process ID is running."""
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if process != 0:
            kernel32.CloseHandle(process)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return False

def is_port_locked(port_name: str) -> bool:
    lock_path = get_lock_filepath(port_name)
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r") as f:
                pid = int(f.read().strip())
            if is_process_running(pid):
                return True
            else:
                os.remove(lock_path)
        except (ValueError, OSError):
            try:
                os.remove(lock_path)
            except OSError:
                pass
    return False

def lock_port(port_name: str):
    lock_path = get_lock_filepath(port_name)
    try:
        with open(lock_path, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass

def unlock_port(port_name: str):
    lock_path = get_lock_filepath(port_name)
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except OSError:
        pass

def acquire_available_port():
    candidate_ports = get_target_ports()
    if not candidate_ports:
        # Fallback for Windows if manufacturer metadata isn't returned by generic COM port drivers
        if os.name == 'nt':
            ports = serial.tools.list_ports.comports()
            candidate_ports = [port.device for port in ports]
            
    if not candidate_ports:
        return None
        
    available = []
    for port in candidate_ports:
        if is_port_locked(port):
            continue
        try:
            test_ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
            test_ser.close()
            available.append(port)
        except (serial.SerialException, PermissionError):
            continue

    if not available:
        return None
        
    if len(available) > 1:
        print("\r\n[+] Multiple active serial interfaces detected:")
        for idx, port in enumerate(available):
            print(f"  [{idx}] {port}\r")
        while True:
            try:
                selection = input(f"Select target port index (0-{len(available)-1}): ").strip()
                selected_idx = int(selection)
                if 0 <= selected_idx < len(available):
                    return available[selected_idx]
            except (ValueError, IndexError):
                pass
            print("[-] Invalid input choice. Please select a valid index number.\r")
            
    return available[0]

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
    print("\r\n" + "="*60)
    print(" LIVE CONSOLE CONNECTION ACTIVE ")
    print(" -> Type commands directly to the hardware device below.")
    print(" -> Press [ Ctrl+S ] at any time to resume automated execution script.")
    print(" -> Press [ Ctrl+K ] at any time to kill the entire program.")
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
                    sys.exit(0)
                elif local_key == '\x13':  # Ctrl + S
                    print("\r\n[+] Resuming background automation script routine...\r\n")
                    return

                ser.write(local_key.encode('utf-8', errors='ignore'))
            time.sleep(0.01)

    except (serial.SerialException, OSError):
        print("\r\n[!] Connection dropped: USB serial cable pulled during terminal interaction.\r")

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
            print("\r\n[!] Program execution killed cleanly via Ctrl+K.\r")
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
    if len(sys.argv) > 1:
        port_name = sys.argv[1]
        if is_port_locked(port_name):
            print(f"[-] Error: Port {port_name} is explicitly locked!\r\n")
            sys.exit(1)
    else:
        port_name = acquire_available_port()
        
    if not port_name:
        print("[-] Error: No unallocated or available serial cable detected!\r\n")
        sys.exit(1)

    lock_port(port_name)
    print(f"[+] Lock acquired for {port_name}\r\n")
    
    try:
        ser = serial.Serial(port_name, BAUD_RATE, timeout=1)
    except Exception as e:
        print(f"[-] Error: Failed to open interface connection: {e}\r\n")
        unlock_port(port_name)
        sys.exit(1)
        
    print("[+] Listening to serial feed. Power on / reboot the switch now...")
    print("    [ Hotkeys active: Ctrl+K = Kill completely | Ctrl+S = Toggle Live Console ]\r\n")

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
                print("\r\n[!] Program execution killed cleanly via Ctrl+K.\r")
                break
                
            if key == '\x13' or isreset: # Ctrl + S
                if not isreset:
                    print("\r\n\r\n[?] Create interactive console screen? (y/n): ", end="", flush=True)
                    confirm = None
                    while confirm is None:
                        confirm = check_keyboard_input()
                        if confirm == '\x0b':
                            sys.exit(0)
                        time.sleep(0.05)
                        
                    if confirm.lower() == 'y':
                        run_interactive_screen(ser)
                    else:
                        print(" Returning back to automatic script loop...\r\n")
                        
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
                print("\r\n[!] CRITICAL: USB Serial Interface Adapter disconnected! Exiting loop framework.\r")
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
                    print("\r\n[+] Juniper login prompt detected\r")
                    ser.write(b"root\n")
                    time.sleep(1)
                    buffer = ""

                elif "password:" in buffer.lower():
                    time.sleep (1)
                    print("\n[+] Prompt detected")
                    ser.write(b"\n")
                    buffer = ""

                elif "Login incorrect" in buffer:
                    buffer = ""
                    islocked = True
                    print("\r\n\r\n" + "!"*65)
                    print(" [!] Target device is booted with an ACTIVE configuration.")
                    print(" [!] ACTION: Power-cycle or flip the hardware switch on the unit now.")
                    print(" [!] Press Ctrl-S when device is power-cycled")
                    print("!"*65 + "\r\n")
                    run_interactive_screen(ser)

                elif "root@:RE:0%" in buffer:
                    time.sleep(1)
                    print("\n[+] Prompt detected")
                    ser.write(b"\n")

                    if send_when(ser, JUNIPER_ROOT):
                        time.sleep(1)
                        if ser.in_waiting > 0:
                            buffer += strip_ansi(ser.read(ser.in_waiting).decode('utf-8', errors='ignore'))
                            
                        chassis_match = re.search(r"Chassis\s+([A-Za-z0-9\-]+)\s+([A-Za-z0-9\-]+)", buffer)
                        dev_modeltag = chassis_match.group(2) if chassis_match else "UNKNOWN MODEL"
                        dev_sertag = chassis_match.group(1) if chassis_match else "UNKNOWN SERIAL"

                        if dev_sertag != "UNKNOWN SERIAL":
                            copy_to_clipboard(dev_sertag)
                            clipboard_status = f" -> Serial Tag: {dev_sertag} (Copied to Clipboard! ✓)"
                        else:
                            clipboard_status = f" -> Serial Tag: {dev_sertag}"
                        
                        print("\r\n" + "*"*40)
                        print(f" DEVICE INVENTORY SUCCESSFUL")
                        print(f" -> Model Tag:  {dev_modeltag}")
                        print(f" -> Serial Tag: {dev_sertag}")
                        print("*"*40 + "\r\n")
                        isreset = True
                        buffer = ""
                    else:
                        print("\r\n\r\n" + "!"*65)
                        print(" [!] WARNING: Target device is booted with an ACTIVE configuration.")
                        print(" [!] Security access is blocked. A clean factory reset is required.")
                        print(" [!] ACTION: Power-cycle or flip the hardware switch on the unit now.")
                        print("!"*65 + "\r\n")
                        
                        autoboot = True
                        isreset = False
                        in_recovery = False
                        break_sequence = True
                        buffer = ""
                        time.sleep(2)

                elif "Press RETURN to get started!" in buffer:
                    print("\n Starting Cisco Device\n")
                    ser.write(b"\n" * 15) 
                    time.sleep(0.5)
                    ser.write(b"\n")
                    buffer = ""

                elif "Would you like to enter the initial configuration dialog? [yes/no]:" in buffer:
                    print("\n Cisco Configuration Dialog Detected\n")
                    ser.write(b"no\n")
                    buffer = ""

                elif "Switch>" in buffer:
                    print("[+] Cisco root CLI detected")
                    ser.write(b"enable\n")

                    if send_when(ser, CISCO_ROOT):
                        time.sleep(1)
                        if ser.in_waiting > 0:
                            buffer += strip_ansi(ser.read(ser.in_waiting).decode('utf-8', errors='ignore'))
                        
                        model_match = re.search(r"Model number\s*:\s*([A-Za-z0-9\-]+)", buffer)
                        dev_modeltag = model_match.group(1) if model_match else "UNKNOWN MODEL"
                        
                        serial_match = re.search(r"System serial number\s*:\s*([A-Za-z0-9\-]+)", buffer)
                        dev_sertag = serial_match.group(1) if serial_match else "UNKNOWN SERIAL"
                        
                        if dev_sertag != "UNKNOWN SERIAL":
                            copy_to_clipboard(dev_sertag)
                            clipboard_status = f" -> Serial Tag: {dev_sertag} (Copied to Clipboard! ✓)"
                        else:
                            clipboard_status = f" -> Serial Tag: {dev_sertag}"
                        
                        print("\r\n" + "*"*40)
                        print(f" DEVICE INVENTORY SUCCESSFUL")
                        print(f" -> Model Tag:  {dev_modeltag}")
                        print(clipboard_status)
                        print("*"*40 + "\r\n")
                        isreset = True
                        buffer = ""

                    else:
                        print("\r\n\r\n" + "!"*65)
                        print(" [!] WARNING: Target device is booted with an ACTIVE configuration.")
                        print(" [!] Security access is blocked. A clean factory reset is required.")
                        print(" [!] ACTION: Power-cycle or flip the hardware switch on the unit now.")
                        print("!"*65 + "\r\n")
                        
                        autoboot = True
                        isreset = False
                        in_recovery = False
                        break_sequence = True
                        buffer = ""
                        time.sleep(2)

                # Juniper Bootloader Check
                elif "Hit [Enter] to boot immediately, or space bar for command prompt." in buffer and autoboot and not isreset:
                    break_sequence = False
                    print("\r\n[+] Juniper bootloader detected! Interrupting autoboot...\r\n")
                    ser.write(b" ")
                    time.sleep(1)
                    ser.write(b"boot -s\n")
                    autoboot = False
                    boottype = "juniper - yes"
                    buffer = ""

                # 1. Catch dynamic countdown (Autoboot in X seconds / Ctrl-C)
                elif re.search(r"(autoboot in|press ctrl-c)", search_buffer, re.IGNORECASE) and autoboot:
                    print("\n[+] Countdown detected! Intercepting with Ctrl-C...")
                    ser.write(b"\x03")
                    autoboot = False
                    buffer = ""

                elif "rommon 1 >" in buffer and not autoboot and not isreset:
                    break_sequence = False
                    print("\r\n[+] Recovery shell detected -> Preparing to send recovery commands...\r\n")
                    ser.write(b"confreg\n")
                    if send_when(ser, CISCO_CONFREG):
                        isreset = True
                        buffer = ""

                # 2. Match Option 5 (More Options)
                elif re.search(r"5\.\s*\[?M\]?ore\s*options", search_buffer, re.IGNORECASE) and not pressed_5 and not isreset:
                    print("\n[+] Found '5. More options'. Sending 5...")
                    ser.write(b"5")
                    pressed_5 = True
                    autoboot = False
                    buffer = ""

                # 3. Match Option 2 (Recovery Mode)
                elif re.search(r"2\.\s*Recovery\s*mode", search_buffer, re.IGNORECASE) and pressed_5 and not pressed_2 and not isreset:
                    print("\n[+] Found '2. Recovery mode'. Sending 2...")
                    ser.write(b"2")
                    pressed_2 = True
                    boottype = "juniper - exit"
                    in_recovery = True
                    buffer = ""

                # Cisco Bootloader Check
                elif "switch:" in buffer and autoboot:
                    break_sequence = False
                    print("[+] Cisco CLI detected! Sending Commands...\r\n")
                    ser.write(b"flash_init\n")
                    if send_when(ser, CISCO_CLI):
                        isreset = True
                        buffer = ""

                # Emergency Prompt Trap
                elif "Enter full pathname of shell or 'recovery'" in buffer:
                    break_sequence = False
                    print("\r\n[+] Intercepting primary recovery prompt -> Routing to Native Recovery Script Tool...\r\n")
                    ser.write(b"recovery\n")
                    in_recovery = True
                    buffer = ""

                # Target prompt verification
                elif "continue, shell, abort, retry, or reboot ?" in buffer and "(fsck -p -y) failed" in buffer:
                    break_sequence = False
                    dev_match = re.search(r"ufs:\s*(/dev/da\d+s\w+)", buffer)
                    dev_target = dev_match.group(1) if dev_match else "/dev/da0s2a"

                    fsck_sequence = [
                        ("#", f"fsck_ffs -y -f {dev_target}"),
                        ("#", "exit")
                    ]

                    print(f"\r\n[!] Storage consistency check verification hanging up on partition: {dev_target}\r\n")
                    ser.write(b"shell\n")                    
                                                 
                    if send_when(ser, fsck_sequence):
                        time.sleep(1)
                        ser.write(b"continue\n")
                        buffer = ""

                    elif "continue, shell, abort, retry, or reboot ?" in buffer and "(mount -a) failed" in buffer:
                        break_sequence = False
                        dev_match = re.search(r"ufs:\s*(/dev/da\d+s\w+)", buffer)
                        dev_target = dev_match.group(1) if dev_match else "/dev/da0s2a"
            
                        fsck_sequence = [
                            ("#", f"fsck_ffs -y -f {dev_target}"),
                            ("#", "exit")
                        ]

                        print(f"\r\n[!] Storage consistency check verification hanging up on partition: {dev_target}\r\n")
                        ser.write(b"shell\n")                    

                        if send_when(ser, fsck_sequence):
                            time.sleep(1)
                            ser.write(b"continue\n")
                            buffer = ""
                
                # Recovery Sequence Execution
                elif "Starting CLI ..." in buffer and in_recovery:
                    break_sequence = False
                    print("\r\n[+] Recovery shell detected -> Preparing to send recovery commands...\r\n")
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
                        ser.write(b"\r\n")
                        ser.write(b"\n")
                        ser.write(b" ")
                    except (serial.SerialException, OSError):
                        print("\r\n[!] CRITICAL: Disconnected during wake-up transmission burst loops.\r")
                        break
                    last_break_time = current_time
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\r\n[+] Script execution paused or cleanly exited via intercept.\r")
    finally:
        if old_settings and os.name != 'nt':
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
        unlock_port(port_name)
        try:
            ser.close()
        except Exception:
            pass
        print(f"[✓] Lock released for {port_name}. Goodbye.\r")

if __name__ == "__main__":
    main()