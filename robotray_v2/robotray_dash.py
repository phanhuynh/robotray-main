"""
550_dash.py (Option 1)
Single-file Dash app that:
  - Connects to TRAY (Ender/stage over USB serial) with robust auto-detect across USB hubs
  - Connects to X-550 RemoteService (localhost ports scan)
  - Shows connection feedback on a simple dashboard

Requirements:
  pip install dash dash-bootstrap-components pyserial requests
"""

import time
import requests
import serial
import serial.tools.list_ports
import base64
import json
import datetime
import os
import re

import dash
from dash import html, dcc, Input, Output, State
import dash_bootstrap_components as dbc

import socket
from typing import Optional, Tuple
# ============================================================
# GLOBAL TEST COUNTER
# ============================================================
CONFIG_FILE = os.path.join(os.path.dirname(__file__), '.robotray_config.json')
TEST_COUNTER = 1  # Will be loaded from config at startup
TRAY_SEQUENCE_ROW = 2  # Current row in tray_sequence.txt (starts at 2, first data row)
_LAST_SEQUENCE3_SUBFOLDER = None  # Populated by Start X; used by Start XB
_LAST_SEQUENCE3_TEST_NUMS = []    # Populated by Start X; used by Start XB
TRAY_SEQUENCE_RUNNING = False  # True while automated tray sequences are executing
LAST_TRAY_POS = None  # Cached latest tray coordinates (x, y, z)

# Tray cup coordinates (will be loaded from config at startup)
FIRST_CUP_X = 10.0
FIRST_CUP_Y = 10.0
LAST_CUP_X = 11.0
LAST_CUP_Y = 9.0

# Basler tray cup coordinates (independent from X550 tray coordinates)
BASLER_FIRST_CUP_X = 10.0
BASLER_FIRST_CUP_Y = 10.0
BASLER_LAST_CUP_X = 11.0
BASLER_LAST_CUP_Y = 9.0

TRAY_WORK_Z = 0.0

# ── Safe movement limits (mm). Adjust to match your physical tray. ──
TRAY_X_MIN =   0.0
TRAY_X_MAX = 130.0 # SET BY PHAN (18 march)
TRAY_Y_MIN = -50.0
TRAY_Y_MAX = 300.0
TRAY_Z_MIN = -20.0
TRAY_Z_MAX =  50.0

# Track last fired test for each sequence to prevent duplicates
MINING_LAST_FIRED = 0
SOIL_LAST_FIRED = 0

def _check_tray_limits(x=None, y=None, z=None):
    """Raise ValueError if any coordinate is outside the configured safe travel limits."""
    if x is not None and not (TRAY_X_MIN <= x <= TRAY_X_MAX):
        raise ValueError(f"X={x} is outside safe range [{TRAY_X_MIN}, {TRAY_X_MAX}]")
    if y is not None and not (TRAY_Y_MIN <= y <= TRAY_Y_MAX):
        raise ValueError(f"Y={y} is outside safe range [{TRAY_Y_MIN}, {TRAY_Y_MAX}]")
    if z is not None and not (TRAY_Z_MIN <= z <= TRAY_Z_MAX):
        raise ValueError(f"Z={z} is outside safe range [{TRAY_Z_MIN}, {TRAY_Z_MAX}]")


def load_test_counter():
    """Load the test counter from config file"""
    global TEST_COUNTER
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                TEST_COUNTER = config.get('test_counter', 1)
                print(f"[CONFIG] Loaded test counter: {TEST_COUNTER}")
    except (json.JSONDecodeError, IOError, ValueError) as e:
        print(f"[CONFIG] Could not load test counter (file may be corrupted): {e}, resetting to 1")
        TEST_COUNTER = 1

def load_cup_coordinates():
    """Load cup coordinates from config file at startup"""
    global FIRST_CUP_X, FIRST_CUP_Y, LAST_CUP_X, LAST_CUP_Y
    global BASLER_FIRST_CUP_X, BASLER_FIRST_CUP_Y, BASLER_LAST_CUP_X, BASLER_LAST_CUP_Y
    global TRAY_WORK_Z
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)

                def _clamp_coord(val, lo, hi, name):
                    if not (lo <= val <= hi):
                        print(f"[CONFIG] WARNING: {name}={val} is outside safe range [{lo}, {hi}], clamping to safe bounds")
                        return max(lo, min(hi, val))
                    return val

                raw_x550_x = float(config.get('x550_first_cup_x', config.get('first_cup_x', FIRST_CUP_X)))
                raw_x550_y = float(config.get('x550_first_cup_y', config.get('first_cup_y', FIRST_CUP_Y)))
                raw_z = float(config.get('tray_work_z', TRAY_WORK_Z))
                FIRST_CUP_X = _clamp_coord(raw_x550_x, TRAY_X_MIN, TRAY_X_MAX, 'x550_first_cup_x')
                FIRST_CUP_Y = _clamp_coord(raw_x550_y, TRAY_Y_MIN, TRAY_Y_MAX, 'x550_first_cup_y')
                TRAY_WORK_Z = _clamp_coord(raw_z, TRAY_Z_MIN, TRAY_Z_MAX, 'tray_work_z')

                # Always recalculate last cup based on formula: X = first_x + 63, Y = first_y - 98
                LAST_CUP_X = FIRST_CUP_X + 63
                LAST_CUP_Y = FIRST_CUP_Y - 98

                raw_b_x = float(config.get('basler_first_cup_x', BASLER_FIRST_CUP_X))
                raw_b_y = float(config.get('basler_first_cup_y', BASLER_FIRST_CUP_Y))
                BASLER_FIRST_CUP_X = _clamp_coord(raw_b_x, TRAY_X_MIN, TRAY_X_MAX, 'basler_first_cup_x')
                BASLER_FIRST_CUP_Y = _clamp_coord(raw_b_y, TRAY_Y_MIN, TRAY_Y_MAX, 'basler_first_cup_y')
                BASLER_LAST_CUP_X = BASLER_FIRST_CUP_X + 63
                BASLER_LAST_CUP_Y = BASLER_FIRST_CUP_Y - 98

                print(f"[CONFIG] Loaded cup coordinates from config file:")
                print(f"[CONFIG] First cup: X={FIRST_CUP_X}, Y={FIRST_CUP_Y}")
                print(f"[CONFIG] Last cup (calculated): X={LAST_CUP_X}, Y={LAST_CUP_Y}")
                print(f"[CONFIG] Basler first cup: X={BASLER_FIRST_CUP_X}, Y={BASLER_FIRST_CUP_Y}")
                print(f"[CONFIG] Basler last cup (calculated): X={BASLER_LAST_CUP_X}, Y={BASLER_LAST_CUP_Y}")
                print(f"[CONFIG] Tray work Z: {TRAY_WORK_Z}")
    except (json.JSONDecodeError, IOError, ValueError) as e:
        print(f"[CONFIG] Could not load cup coordinates: {e}")
        # Use defaults already initialized above
        print(f"[CONFIG] Using default cup coordinates:")
        print(f"[CONFIG] First cup: X={FIRST_CUP_X}, Y={FIRST_CUP_Y}")
        print(f"[CONFIG] Last cup: X={LAST_CUP_X}, Y={LAST_CUP_Y}")
        print(f"[CONFIG] Basler first cup: X={BASLER_FIRST_CUP_X}, Y={BASLER_FIRST_CUP_Y}")
        print(f"[CONFIG] Basler last cup: X={BASLER_LAST_CUP_X}, Y={BASLER_LAST_CUP_Y}")
        print(f"[CONFIG] Tray work Z: {TRAY_WORK_Z}")


def load_config_dict() -> dict:
    """Load config JSON safely; return empty dict if missing/corrupted."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError, ValueError):
        return {}


def save_config_dict(config: dict) -> None:
    """Persist config with atomic write and small retry for Windows file locking."""
    max_retries = 3
    retry_delay = 0.05
    temp_file = CONFIG_FILE + ".tmp"

    for attempt in range(max_retries):
        try:
            with open(temp_file, 'w') as f:
                json.dump(config, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, CONFIG_FILE)
            return
        except Exception:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise

def get_next_test_number():
    """Get the next test number and increment the counter"""
    global TEST_COUNTER
    current = TEST_COUNTER
    TEST_COUNTER += 1
    
    # Save updated counter to config with atomic write (write to temp, then rename)
    # Use retry logic to handle Windows file locking
    max_retries = 3
    retry_delay = 0.05  # 50ms delay between retries
    
    for attempt in range(max_retries):
        try:
            config = {}
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, 'r') as f:
                        config = json.load(f)
                except (json.JSONDecodeError, IOError):
                    # File is corrupted, start fresh
                    config = {}
            
            config['test_counter'] = TEST_COUNTER
            
            # Write to temp file first
            temp_file = CONFIG_FILE + ".tmp"
            with open(temp_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Atomic rename - delete old file first on Windows
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            import shutil
            shutil.move(temp_file, CONFIG_FILE)
            break  # Success, exit retry loop
        except Exception as e:
            if attempt < max_retries - 1:
                # Retry with delay
                import time
                time.sleep(retry_delay)
            else:
                # Final attempt failed, just log it
                print(f"[CONFIG] Could not save test counter: {e}")
    
    return current


# ============================================================
# BUTTON CLICK LOGGER
# ============================================================

def log_button_click(button_name, is_button=True, **kwargs):
    """Log button clicks or events to a text file with timestamp"""
    # Use SAVED_FOLDER if configured; create it if missing
    log_dir = None
    if SAVED_FOLDER:
        try:
            os.makedirs(SAVED_FOLDER, exist_ok=True)
            log_dir = SAVED_FOLDER
        except Exception as e:
            print(f"[LOG] Could not create SAVED_FOLDER for logs: {e}")
            log_dir = None
    if not log_dir:
        log_dir = os.path.dirname(__file__)
    
    log_file = os.path.join(log_dir, 'dashboard_clicks.log')
    backup_log_file = os.path.join(log_dir, 'dashboard_clicks_backup.log')
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    if is_button:
        log_entry = f"[{timestamp}] Button: {button_name}"
    else:
        log_entry = f"[{timestamp}] {button_name}"
    
    # Add any additional info passed as kwargs
    if kwargs:
        details = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
        log_entry += f" | {details}"
    
    log_entry += "\n"
    
    # Try main log file first
    try:
        with open(log_file, 'a') as f:
            f.write(log_entry)
            f.flush()  # Force write to disk
        print(f"[LOG] {log_entry.strip()}")
    except (PermissionError, IOError) as e:
        # If main log is locked, use backup
        try:
            with open(backup_log_file, 'a') as f:
                f.write(log_entry)
                f.flush()  # Force write to disk
            print(f"[LOG-BACKUP] {log_entry.strip()}")
        except Exception as e:
            print(f"[LOG] Error logging button click (both files): {e}")
    except Exception as e:
        print(f"[LOG] Error logging button click: {e}")


# ============================================================
# PORT AND CONNECTION HELPERS
# ============================================================

def find_x550_port(start_port: int = 8070, end_port: int = 8090) -> Optional[str]:
    """Scan for X550 RemoteService on a range of ports"""
    for port in range(start_port, end_port + 1):
        for path in ("/api/v2/id", "/api/v1/id", "/api/id"):
            url = f"http://127.0.0.1:{port}{path}"
            try:
                r = requests.get(url, timeout=0.5)
                if r.status_code == 200:
                    print(f"[X550] Found RemoteService at {url}")
                    return f"http://127.0.0.1:{port}"
            except (requests.RequestException, socket.error):
                pass
    return None


# ============================================================
# TRAY PORT DETECTION (robust across different USB hubs)
# ============================================================

def find_tray_port(
    tray_usb_serial: Optional[str] = None,
    prefer_vidpid: Tuple[str, ...] = ("1A86:7523", "10C4:EA60", "0403:6001"),  # CH340, CP210x, FTDI
    prefer_keywords: Tuple[str, ...] = ("CREALITY", "ENDER", "CH340", "CP210", "USB-SERIAL", "USB SERIAL", "UART"),
) -> Optional[str]:
    """
    Stable selection across hubs:
      1) Exact USB serial_number (if you configure it)
      2) VID:PID match in hwid
      3) Keyword match in description/manufacturer
    """
    ports = list(serial.tools.list_ports.comports())

    # 1) Exact match by USB serial number (best if available)
    if tray_usb_serial:
        for p in ports:
            if getattr(p, "serial_number", None) == tray_usb_serial:
                print(f"[TRAY] Selected by serial_number={tray_usb_serial}: {p.device}")
                return p.device
        print(f"[TRAY] No port matched tray_usb_serial={tray_usb_serial}")

    # 2) Match by VID:PID
    for p in ports:
        hwid = (p.hwid or "").upper()
        for vp in prefer_vidpid:
            if vp.upper() in hwid:
                print(f"[TRAY] Selected by VID:PID {vp}: {p.device} ({p.description})")
                return p.device

    # 3) Keyword match
    for p in ports:
        desc = ((p.description or "") + " " + (getattr(p, "manufacturer", "") or "")).upper()
        for kw in prefer_keywords:
            if kw.upper() in desc:
                print(f"[TRAY] Selected by keyword '{kw}': {p.device} ({p.description})")
                return p.device

    return None


# ============================================================
# TRAY CONNECTION (USB serial -> G-code)
# ============================================================

class TrayConnection:
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 2.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None

    def connect(self) -> bool:
        try:
            self.ser = serial.Serial(
                self.port,
                self.baudrate,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
            time.sleep(2.0)  # board reset
            self._send("M115")  # benign handshake (firmware info)
            print(f"[TRAY] Connected: {self.port}")
            return True
        except serial.SerialException as e:
            if "PermissionError" in str(e) or "Access is denied" in str(e):
                print(f"[TRAY] COM4 is already in use by another program!")
                print(f"[TRAY] Check: Arduino IDE, PuTTY, Cura, OctoPrint, or other Python scripts")
                print(f"[TRAY] Error: {e}")
            else:
                print(f"[TRAY] Connection failed on {self.port}: {e}")
                import traceback
                traceback.print_exc()
            self.ser = None
            return False
        except Exception as e:
            print(f"[TRAY] Connection failed on {self.port}: {e}")
            print(f"[TRAY] Error type: {type(e).__name__}")
            import traceback
            traceback.print_exc()
            self.ser = None
            return False

    def _reopen_serial(self):
        """Try to recover serial connection in-place after transient USB/driver faults."""
        try:
            if self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
        except Exception:
            self.ser = None

        self.ser = serial.Serial(
            self.port,
            self.baudrate,
            timeout=self.timeout,
            write_timeout=self.timeout,
        )
        time.sleep(0.2)

    def _send(self, cmd: str):
        if not self.ser:
            raise RuntimeError("Tray not connected")
        payload = (cmd + "\n").encode()

        # One recovery retry for transient COM write timeout/disconnect.
        for attempt in range(2):
            try:
                self.ser.write(payload)
                self.ser.flush()
                return
            except (serial.SerialTimeoutException, serial.SerialException, OSError) as e:
                if attempt == 0:
                    print(f"[TRAY] Write failed for '{cmd}', trying reopen: {e}")
                    try:
                        self._reopen_serial()
                        continue
                    except Exception as reconnect_error:
                        raise RuntimeError(f"Tray reconnect failed after write error: {reconnect_error}") from e
                raise RuntimeError(f"Tray write failed for '{cmd}': {e}") from e
    
    def _read_response(self, timeout: float = 2.0) -> str:
        """Read response lines until 'ok' or timeout"""
        if not self.ser:
            raise RuntimeError("Tray not connected")
        lines = []
        start = time.time()
        found_ok = False
        while time.time() - start < timeout:
            try:
                line = self.ser.readline().decode(errors="ignore").strip()
            except Exception:
                line = ""
            if line:
                lines.append(line)
                if line.lower().startswith("ok"):
                    found_ok = True
                    break
            elif found_ok:
                # If we found ok and now get empty line, we're done
                break
        return "\n".join(lines)

    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def disconnect(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def home(self):
        self._send("G28 X Y")
        self._read_response()

    def is_z_min_triggered(self) -> Optional[bool]:
        """Return True/False if Z-min endstop state can be parsed, else None."""
        self._send("M119")
        resp = self._read_response(timeout=1.0)
        text = resp.lower()
        # Common Marlin format: "z_min: open" or "z_min: triggered"
        match = re.search(r"z[_\-\s]*min\s*:\s*(open|triggered)", text)
        if not match:
            return None
        return match.group(1) == "triggered"

    def lower_z_until_threshold(self, step_mm: float = 0.5, max_travel_mm: float = 40.0, feedrate: int = 1200) -> Tuple[bool, float, str]:
        """Jog Z downward in small relative steps until Z-min endstop is triggered.
        Returns: (triggered, moved_mm, reason)
        """
        if step_mm <= 0:
            raise ValueError("step_mm must be > 0")
        if max_travel_mm <= 0:
            raise ValueError("max_travel_mm must be > 0")

        endstop_state = self.is_z_min_triggered()
        if endstop_state is None:
            return False, 0.0, "z-min status unavailable"
        if endstop_state:
            return True, 0.0, "z-min already triggered"

        moved = 0.0
        steps = int(max_travel_mm / step_mm)

        self._send("G91")  # relative mode for jogging
        self._read_response(timeout=0.5)
        try:
            for _ in range(steps):
                self._send(f"G0 Z-{step_mm} F{feedrate}")
                self._read_response(timeout=1.0)
                moved += step_mm

                endstop_state = self.is_z_min_triggered()
                if endstop_state is True:
                    return True, moved, "z-min triggered"
                if endstop_state is None:
                    return False, moved, "z-min status unavailable during move"

            return False, moved, "max travel reached without trigger"
        finally:
            self._send("G90")  # restore absolute mode
            self._read_response(timeout=0.5)

    def goto(self, x: Optional[float] = None, y: Optional[float] = None, z: Optional[float] = None, f: int = 3000):
        _check_tray_limits(x=x, y=y, z=z)
        parts = ["G0"]
        if x is not None:
            parts.append(f"X{x}")
        if y is not None:
            parts.append(f"Y{y}")
        if z is not None:
            parts.append(f"Z{z}")
        if f:
            parts.append(f"F{f}")

        # Absolute moves must not inherit stale serial replies or an old G91 state.
        if self.ser:
            try:
                self.ser.reset_input_buffer()
            except Exception:
                pass
        time.sleep(0.05)

        self._send("G90")
        self._read_response(timeout=0.6)
        self._send(" ".join(parts))
        self._read_response(timeout=1.2)

    def get_position(self, strict: bool = False) -> Tuple[float, float, float]:
        import re
        def extract_xyz(text: str):
            patterns = [
                r"X:\s*(-?\d*\.?\d+)\s*Y:\s*(-?\d*\.?\d+)\s*Z:\s*(-?\d*\.?\d+)",
                r"X[.:]?\s*(-?\d+\.?\d*)\s*Y[.:]?\s*(-?\d+\.?\d*)\s*Z[.:]?\s*(-?\d+\.?\d*)",
            ]
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    return float(match.group(1)), float(match.group(2)), float(match.group(3))
            return None

        last_resp = ""

        attempts = 5 if strict else 1

        for attempt in range(attempts):
            # Only strict mode waits for planner queue to empty.
            if strict:
                try:
                    self._send("M400")
                    # Drain the full M400 response, then wait for any trailing bytes
                    self._read_response(timeout=1.2)
                    time.sleep(0.15)
                except Exception:
                    pass

            # Clear pending serial data before query, then pause so any
            # in-flight bytes finish arriving before we send M114.
            if self.ser:
                try:
                    self.ser.reset_input_buffer()
                except Exception:
                    try:
                        while self.ser.in_waiting > 0:
                            self.ser.read(1)
                    except Exception:
                        pass
            time.sleep(0.1)  # let firmware finish transmitting stale data

            self._send("M114")

            # Collect response chunks; strict mode allows longer collection.
            chunks = []
            t0 = time.time()
            collect_window = 1.8 if strict else 0.35
            read_timeout = 0.35 if strict else 0.15
            while time.time() - t0 < collect_window:
                resp_part = self._read_response(timeout=read_timeout)
                if resp_part:
                    chunks.append(resp_part)
                    combined = "\n".join(chunks)
                    xyz = extract_xyz(combined)
                    if xyz is not None:
                        return xyz
                else:
                    if not strict:
                        break
                    time.sleep(0.03)

            if chunks:
                last_resp = " | ".join(chunks)
            if strict:
                time.sleep(0.12)

        raise ValueError(f"Could not parse position from M114 response after retries. Got: '{last_resp}'")


# ============================================================
# X-550 CONNECTION (RemoteService HTTP)
# ============================================================

class X550Connection:
    def __init__(self, host: str = "127.0.0.1", port_start: int = 8070, port_end: int = 8090):
        self.host = host
        self.port_start = port_start
        self.port_end = port_end
        self.base_url: Optional[str] = None
        self.api_root: Optional[str] = None  # "/api/v2" or "/api/v1" or "/api"
        self.last_heartbeat_ok: bool = False
        self.last_heartbeat_time: Optional[float] = None

    def connect(self) -> bool:
        print(f"[X550] Scanning {self.host} ports {self.port_start}-{self.port_end} for RemoteService...")
        ports = [8080] + [p for p in range(self.port_start, self.port_end + 1) if p != 8071]
        for port in ports:
            for path in ("/api/v2/id", "/api/v1/id", "/api/id"):
                url = f"http://{self.host}:{port}{path}"
                try:
                    r = requests.get(url, timeout=2.0)
                    if r.status_code != 200:
                        continue

                    content_type = (r.headers.get("Content-Type") or "").lower()
                    try:
                        data = r.json() if "json" in content_type else json.loads(r.text)
                    except Exception:
                        continue

                    if not isinstance(data, dict):
                        continue

                    if "family" not in data and "apps" not in data:
                        continue

                    self.base_url = f"http://{self.host}:{port}"
                    self.api_root = path.rsplit("/", 1)[0]
                    print(f"[X550] ✓ Connected to {self.base_url}")
                    self.last_heartbeat_ok = True
                    self.last_heartbeat_time = time.time()
                    return True
                except requests.RequestException:
                    pass

        print(f"[X550] No RemoteService found on {self.host}:{self.port_start}-{self.port_end}")
        self.base_url = None
        self.api_root = None
        self.last_heartbeat_ok = False
        return False

    def is_connected(self) -> bool:
        return self.base_url is not None
    
    def heartbeat(self) -> bool:
        """Check if X550 is still responding"""
        if not self.is_connected():
            self.last_heartbeat_ok = False
            return False
        
        try:
            url = f"{self.base_url}{self.api_root}/id"
            r = requests.get(url, timeout=2)
            self.last_heartbeat_ok = (r.status_code == 200)
            self.last_heartbeat_time = time.time()
            return self.last_heartbeat_ok
        except requests.RequestException as e:
            print(f"[X550] Heartbeat failed: {e}")
            self.last_heartbeat_ok = False
            return False


# ============================================================
# SYSTEM CONNECT (Step 1 of your flow)
# ============================================================

# GLOBAL singletons (top of file)
_TRAY_INSTANCE = None
_X550_INSTANCE = None
_BASLER_INSTANCE = None


def _reset_basler_instance():
    """Safely stop/close and clear cached Basler camera instance."""
    global _BASLER_INSTANCE
    if _BASLER_INSTANCE is None:
        return
    try:
        if _BASLER_INSTANCE.IsGrabbing():
            _BASLER_INSTANCE.StopGrabbing()
    except Exception:
        pass
    try:
        if _BASLER_INSTANCE.IsOpen():
            _BASLER_INSTANCE.Close()
    except Exception:
        pass
    _BASLER_INSTANCE = None


def _open_first_basler_camera():
    """Open first available Basler camera and cache it."""
    global _BASLER_INSTANCE
    from pypylon import pylon

    tl_factory = pylon.TlFactory.GetInstance()
    devices = tl_factory.EnumerateDevices()
    if len(devices) == 0:
        return None, "No Basler cameras found"

    camera = pylon.InstantCamera(tl_factory.CreateDevice(devices[0]))
    camera.Open()
    _BASLER_INSTANCE = camera
    camera_model = camera.GetDeviceInfo().GetModelName()
    return camera_model, None


def _restart_basler_grabbing_latest():
    """Restart Basler grabbing in latest-image-only mode to minimize stale buffered frames."""
    global _BASLER_INSTANCE
    if _BASLER_INSTANCE is None:
        camera_model, open_error = _open_first_basler_camera()
        if open_error:
            raise RuntimeError(open_error)
        print(f"[BASLER] Reconnected to {camera_model}")

    from pypylon import pylon

    try:
        if _BASLER_INSTANCE.IsGrabbing():
            _BASLER_INSTANCE.StopGrabbing()
    except Exception:
        pass

    time.sleep(0.05)
    _BASLER_INSTANCE.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

def connect_all(tray_usb_serial=None, tray_port_override=None):
    global _TRAY_INSTANCE, _X550_INSTANCE

    # If already connected, reuse
    if _TRAY_INSTANCE and _TRAY_INSTANCE.is_connected() and \
       _X550_INSTANCE and _X550_INSTANCE.is_connected():
        return {
            "tray_connected": True,
            "x550_connected": True,
            "ready": True,
            "tray_port": _TRAY_INSTANCE.port,
            "x550_url": _X550_INSTANCE.base_url,
            "error": None,
        }

    # ---- normal connect path below ----
    if tray_port_override:
        tray_port = tray_port_override
    else:
        tray_port = find_tray_port(tray_usb_serial)

    if not tray_port:
        return {
            "tray_connected": False,
            "x550_connected": False,
            "ready": False,
            "tray_port": None,
            "x550_url": None,
            "error": "Tray not found",
        }

    tray = TrayConnection(tray_port)

    tray_ok = tray.connect()

    if tray_ok:
        _TRAY_INSTANCE = tray

    return {
        "tray_connected": tray_ok,
        "x550_connected": False,  # X550 disabled by default
        "ready": tray_ok,
        "tray_port": tray_port,
        "x550_url": None,
        "error": None if tray_ok else "Tray connection failed",
    }

def connect_x550(host: str = "127.0.0.1", port_override: Optional[int] = None):
    """Connect to X550 RemoteService"""
    global _X550_INSTANCE
    
    # If already connected, reuse
    if _X550_INSTANCE and _X550_INSTANCE.is_connected():
        return {
            "x550_connected": True,
            "x550_url": _X550_INSTANCE.base_url,
            "error": None,
        }
    
    # Handle empty host - use default
    if not host or host.strip() == "":
        host = "127.0.0.1"
    
    # Build candidates list, prioritizing network IP
    candidates = []
    
    if host in ("127.0.0.1", "localhost"):
        if port_override is None:
            # Try network IP FIRST (where X550 actually is)
            candidates.extend([
                ("192.168.42.129", 8080),
                ("192.168.42.1", 8080),
            ])
        # Then try localhost
        candidates.append(("127.0.0.1", port_override))
    else:
        # Custom host specified
        candidates.append((host, port_override))

    print(f"[X550] Connection candidates (in order): {candidates}")
    
    last_error = None
    for cand_host, cand_port in candidates:
        if cand_port is not None:
            x550 = X550Connection(host=cand_host, port_start=cand_port, port_end=cand_port)
        else:
            x550 = X550Connection(host=cand_host)
        
        print(f"[X550] Trying {cand_host}:{cand_port or '8070-8090'}...")
        x550_ok = x550.connect()

        if x550_ok:
            _X550_INSTANCE = x550
            print(f"[X550] SUCCESS - Connected to {x550.base_url}")
            return {
                "x550_connected": True,
                "x550_url": x550.base_url,
                "error": None,
            }

        last_error = f"No RemoteService on {cand_host}:{cand_port or '8070-8090'}"

    checked = ", ".join([f"{h}:{p or '8070-8090'}" for h, p in candidates])
    error_msg = f"X550 not found (checked {checked})"
    print(f"[X550] FAILED - {error_msg}")
    return {
        "x550_connected": False,
        "x550_url": None,
        "error": error_msg,
    }

def connect_basler():
    """Connect to Basler camera using pypylon"""
    global _BASLER_INSTANCE
    
    try:
        import pypylon

        # Reuse only if it is still open and valid
        if _BASLER_INSTANCE is not None:
            try:
                if _BASLER_INSTANCE.IsOpen():
                    camera_model = _BASLER_INSTANCE.GetDeviceInfo().GetModelName()
                    return {
                        "basler_connected": True,
                        "basler_info": f"Camera: {camera_model}",
                        "error": None,
                    }
            except Exception:
                _reset_basler_instance()

        camera_model, open_error = _open_first_basler_camera()
        if open_error:
            return {
                "basler_connected": False,
                "basler_info": None,
                "error": open_error,
            }

        print(f"[BASLER] SUCCESS - Connected to {camera_model}")
        
        return {
            "basler_connected": True,
            "basler_info": f"Camera: {camera_model}",
            "error": None,
        }
    except ImportError:
        return {
            "basler_connected": False,
            "basler_info": None,
            "error": "pypylon not installed (pip install pypylon opencv-python)",
        }
    except Exception as e:
        _reset_basler_instance()
        print(f"[BASLER] FAILED - {e}")
        import traceback
        traceback.print_exc()
        return {
            "basler_connected": False,
            "basler_info": None,
            "error": f"Basler connection error: {e}",
        }



# ============================================================
# DASH APP (connection dashboard)
# ============================================================

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "X550 + Tray - Connection"

# Disable caching to force browser refresh
@app.server.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# Layout will be set in __main__ block

app.clientside_callback(
    """
    function(n_intervals, currentData) {
        if (!window.__robotrayKeyboardState) {
            window.__robotrayKeyboardState = { seq: 0, pending: null };
        }

        if (!window.__robotrayKeyboardListenerAttached) {
            window.addEventListener('keydown', function(e) {
                const k = e.key;
                const valid = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'o', 'O', 'p', 'P'];
                if (!valid.includes(k)) {
                    return;
                }
                if (e.repeat) {
                    return;
                }

                // Prevent browser default behavior for arrow keys (scrolling)
                if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(k)) {
                    e.preventDefault();
                }

                window.__robotrayKeyboardState.seq += 1;
                window.__robotrayKeyboardState.pending = {
                    key: k,
                    seq: window.__robotrayKeyboardState.seq,
                    ts: Date.now()
                };
            }, true);
            window.__robotrayKeyboardListenerAttached = true;
        }

        const pending = window.__robotrayKeyboardState.pending;
        const lastSeq = (currentData && currentData.seq) ? currentData.seq : 0;
        if (!pending || pending.seq <= lastSeq) {
            return window.dash_clientside.no_update;
        }
        return pending;
    }
    """,
    Output("store-keyboard", "data"),
    Input("keyboard-poll", "n_intervals"),
    State("store-keyboard", "data"),
)


@app.callback(
    Output("store-connection", "data"),
    Input("btn-connect", "n_clicks"),
    prevent_initial_call=True,
)
def on_connect(_n_clicks):
    """
    USER: clicks Connect
    TRAY: connect (auto-detect port)
    X550: connect (scan ports)
    """
    log_button_click("Connect to Tray")
    print("\n" + "="*60)
    print("[CONNECT] CONNECT BUTTON CLICKED - Callback started")
    print("="*60)
    
    try:
        # If you later want to lock to a specific USB serial number:
        # TRAY_USB_SERIAL = "PASTE_SERIAL_HERE"
        TRAY_USB_SERIAL = None

        # If you later want to force a known COM port:
        TRAY_PORT_OVERRIDE = None

        data = connect_all(tray_usb_serial=TRAY_USB_SERIAL, tray_port_override=TRAY_PORT_OVERRIDE)

        if data.get("tray_connected") and _TRAY_INSTANCE and _TRAY_INSTANCE.is_connected():
            try:
                print("[CONNECT] Tray connected. Auto-homing X/Y...")
                _TRAY_INSTANCE.home()
                print("[CONNECT] Auto-home complete")
            except Exception as home_err:
                print(f"[CONNECT] WARNING: Auto-home failed: {home_err}")
                data["error"] = f"Connected, but auto-home failed: {home_err}"

        print(f"[CONNECT] CONNECT CALLBACK COMPLETE - Result: {data}")
        return data
    except Exception as e:
        print(f"[ERROR] CONNECT CALLBACK FAILED: {e}")
        import traceback
        traceback.print_exc()
        return {
            "tray_connected": False,
            "x550_connected": False,
            "ready": False,
            "error": f"Connection error: {e}"
        }


@app.callback(
    Output("store-x550", "data"),
    Input("btn-connect-x550", "n_clicks"),
    State("x550-ip", "value"),
    State("x550-port", "value"),
    prevent_initial_call=True,
)
def on_connect_x550(_n_clicks, x550_ip, x550_port):
    """Connect to X550 RemoteService on demand"""
    log_button_click("Connect to X550", ip=x550_ip if x550_ip else "auto", port=x550_port if x550_port else "auto")
    print("\n" + "="*60)
    print("CONNECT X550 BUTTON CLICKED")
    print("="*60)
    
    try:
        host = (x550_ip or "127.0.0.1").strip()
        port_override = None
        if x550_port not in (None, ""):
            try:
                port_override = int(x550_port)
            except ValueError:
                port_override = None

        data = connect_x550(host=host, port_override=port_override)
        print(f"X550 CONNECT COMPLETE - Result: {data}")
        return data
    except Exception as e:
        print(f"X550 CONNECT FAILED: {e}")
        import traceback
        traceback.print_exc()
        return {
            "x550_connected": False,
            "x550_url": None,
            "error": f"X550 connection error: {e}"
        }


@app.callback(
    Output("store-basler", "data"),
    Input("btn-connect-basler", "n_clicks"),
    prevent_initial_call=True,
)
def on_connect_basler(_n_clicks):
    """Connect to Basler camera on demand"""
    log_button_click("Connect to Basler")
    print("\n" + "="*60)
    print("CONNECT BASLER BUTTON CLICKED")
    print("="*60)
    
    try:
        data = connect_basler()
        print(f"BASLER CONNECT COMPLETE - Result: {data}")
        return data
    except Exception as e:
        print(f"BASLER CONNECT FAILED: {e}")
        import traceback
        traceback.print_exc()
        return {
            "basler_connected": False,
            "basler_info": None,
            "error": f"Basler connection error: {e}"
        }


@app.callback(
    Output("video-capture-timer", "disabled"),
    Input("btn-video", "n_clicks"),
    State("video-capture-timer", "disabled"),
    State("store-basler", "data"),
    prevent_initial_call=True,
)
def toggle_video(_n_clicks, is_disabled, basler_data):
    """Toggle video capture on/off"""
    log_button_click("Video")
    
    # Check if Basler is connected
    if not basler_data or not basler_data.get("basler_connected"):
        print("[VIDEO] Basler not connected, cannot start video")
        return True
    
    # Toggle the disabled state
    new_disabled = not is_disabled
    print(f"[VIDEO] Video {'disabled' if new_disabled else 'enabled'}")
    return new_disabled


@app.callback(
    Output("store-video-zoom", "data"),
    Input("btn-zoom-in", "n_clicks"),
    Input("btn-zoom-out", "n_clicks"),
    State("store-video-zoom", "data"),
    prevent_initial_call=True,
)
def update_zoom(n_in, n_out, zoom):
    """Adjust zoom level between 0.5x and 4x"""
    from dash import ctx as dash_ctx
    triggered = dash_ctx.triggered_id
    zoom = zoom or 1.0
    if triggered == "btn-zoom-in":
        zoom = min(zoom * 1.25, 4.0)
    elif triggered == "btn-zoom-out":
        zoom = max(zoom / 1.25, 0.25)
    print(f"[VIDEO] Zoom level: {zoom:.2f}")
    return round(zoom, 4)


@app.callback(
    Output("basler-video-frame", "children"),
    Input("video-capture-timer", "n_intervals"),
    State("store-basler", "data"),
    State("store-video-zoom", "data"),
)
def capture_basler_video(n_intervals, basler_data, zoom):
    """Capture frame from Basler camera and display"""
    if not basler_data or not basler_data.get("basler_connected"):
        return html.Div("Camera not connected", className="text-danger")    
    try:
        if _BASLER_INSTANCE is None:
            camera_model, open_error = _open_first_basler_camera()
            if open_error:
                return html.Div(open_error, className="text-danger")
            print(f"[VIDEO] Reconnected to Basler: {camera_model}")
        
        # Grab frame from camera
        if _BASLER_INSTANCE.IsGrabbing():
            grab_result = _BASLER_INSTANCE.RetrieveResult(5000)
            
            if grab_result.GrabSucceeded():
                # Convert image to numpy array
                image = grab_result.GetArray()
                pixel_format = ""
                try:
                    pixel_format = str(_BASLER_INSTANCE.PixelFormat.GetValue())
                except Exception:
                    pixel_format = ""
                grab_result.Release()
                
                # Convert to RGB for display (handle Bayer, mono, and BGR/RGB outputs)
                import cv2
                if len(image.shape) == 2:
                    fmt = pixel_format.lower()
                    if "bayer" in fmt:
                        if "rg" in fmt:
                            image_rgb = cv2.cvtColor(image, cv2.COLOR_BAYER_RG2RGB)
                        elif "gr" in fmt:
                            image_rgb = cv2.cvtColor(image, cv2.COLOR_BAYER_GR2RGB)
                        elif "gb" in fmt:
                            image_rgb = cv2.cvtColor(image, cv2.COLOR_BAYER_GB2RGB)
                        elif "bg" in fmt:
                            image_rgb = cv2.cvtColor(image, cv2.COLOR_BAYER_BG2RGB)
                        else:
                            image_rgb = cv2.cvtColor(image, cv2.COLOR_BAYER_RG2RGB)
                    else:
                        image_rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
                elif len(image.shape) == 3 and image.shape[2] == 3:
                    fmt = pixel_format.lower()
                    if "rgb" in fmt:
                        image_rgb = image
                    else:
                        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                else:
                    image_rgb = image
                
                # Downscale image to 640x480 for faster transmission
                height, width = image_rgb.shape[:2]
                
                # Apply zoom by cropping the center
                zoom = zoom or 1.0
                if zoom != 1.0:
                    crop_w = int(width / zoom)
                    crop_h = int(height / zoom)
                    x1 = (width - crop_w) // 2
                    y1 = (height - crop_h) // 2
                    image_rgb = image_rgb[y1:y1+crop_h, x1:x1+crop_w]
                
                if width > 640 or height > 480:
                    image_rgb = cv2.resize(image_rgb, (640, 480), interpolation=cv2.INTER_LINEAR)
                
                # Encode image to JPEG with lower quality for faster compression
                _, buffer = cv2.imencode('.jpg', image_rgb, [cv2.IMWRITE_JPEG_QUALITY, 70])
                img_base64 = base64.b64encode(buffer).decode()
                
                return html.Img(
                    src=f"data:image/jpeg;base64,{img_base64}",
                    id="basler-video-img",
                    style={"width": "100%", "border": "2px solid #bdbdbd", "backgroundColor": "#f2f2f2"}
                )
            else:
                grab_result.Release()
                return html.Div("Failed to grab frame", className="text-danger")
        else:
            # Start continuous grabbing
            _BASLER_INSTANCE.StartGrabbing()
            return html.Div("Starting video stream...", className="text-info")
    
    except Exception as e:
        msg = str(e)
        if "physically removed" in msg.lower() or "runtimeexception" in msg.lower():
            print("[VIDEO] Stale/disconnected camera handle detected, resetting Basler instance")
            _reset_basler_instance()
            return html.Div("Camera connection lost. Close Pylon Viewer, then click Video again.", className="text-warning")
        print(f"[VIDEO] Error capturing frame: {e}")
        import traceback
        traceback.print_exc()
        return html.Div(f"Error: {str(e)}", className="text-danger")


@app.callback(
    Output("basler-photo-frame", "children"),
    Input("btn-video-photo", "n_clicks"),
    State("store-basler", "data"),
    State("store-video-zoom", "data"),
    prevent_initial_call=True,
)
def capture_basler_photo(_n_clicks, basler_data, zoom):
    """Capture a still photo from Basler camera and show it next to live video."""
    log_button_click("Photo")

    if not basler_data or not basler_data.get("basler_connected"):
        return html.Div("Camera not connected", className="text-danger")

    try:
        if _BASLER_INSTANCE is None:
            camera_model, open_error = _open_first_basler_camera()
            if open_error:
                return html.Div(open_error, className="text-danger")
            print(f"[PHOTO] Reconnected to Basler: {camera_model}")

        _restart_basler_grabbing_latest()

        grab_result = _BASLER_INSTANCE.RetrieveResult(5000)
        if not grab_result.GrabSucceeded():
            grab_result.Release()
            return html.Div("Failed to capture photo", className="text-danger")

        import cv2
        image = grab_result.GetArray()
        pixel_format = ""
        try:
            pixel_format = str(_BASLER_INSTANCE.PixelFormat.GetValue())
        except Exception:
            pixel_format = ""
        grab_result.Release()

        if len(image.shape) == 2:
            fmt = pixel_format.lower()
            if "bayer" in fmt:
                if "rg" in fmt:
                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BAYER_RG2RGB)
                elif "gr" in fmt:
                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BAYER_GR2RGB)
                elif "gb" in fmt:
                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BAYER_GB2RGB)
                elif "bg" in fmt:
                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BAYER_BG2RGB)
                else:
                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BAYER_RG2RGB)
            else:
                image_rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        elif len(image.shape) == 3 and image.shape[2] == 3:
            fmt = pixel_format.lower()
            if "rgb" in fmt:
                image_rgb = image
            else:
                image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            image_rgb = image

        height, width = image_rgb.shape[:2]
        zoom = zoom or 1.0
        if zoom != 1.0:
            crop_w = int(width / zoom)
            crop_h = int(height / zoom)
            x1 = (width - crop_w) // 2
            y1 = (height - crop_h) // 2
            image_rgb = image_rgb[y1:y1+crop_h, x1:x1+crop_w]

        if width > 640 or height > 480:
            image_rgb = cv2.resize(image_rgb, (640, 480), interpolation=cv2.INTER_LINEAR)

        _, buffer = cv2.imencode('.jpg', image_rgb, [cv2.IMWRITE_JPEG_QUALITY, 90])
        img_base64 = base64.b64encode(buffer).decode()

        try:
            if _BASLER_INSTANCE.IsGrabbing():
                _BASLER_INSTANCE.StopGrabbing()
        except Exception:
            pass

        return html.Img(
            src=f"data:image/jpeg;base64,{img_base64}",
            id="basler-photo-img",
            style={"width": "100%", "border": "2px solid #9e9e9e", "backgroundColor": "#f2f2f2"}
        )

    except Exception as e:
        msg = str(e)
        if "physically removed" in msg.lower() or "runtimeexception" in msg.lower():
            print("[PHOTO] Stale/disconnected camera handle detected, resetting Basler instance")
            _reset_basler_instance()
            return html.Div("Camera connection lost. Close Pylon Viewer, then click Photo again.", className="text-warning")

        print(f"[PHOTO] Error capturing photo: {e}")
        import traceback
        traceback.print_exc()
        return html.Div(f"Error: {str(e)}", className="text-danger")


def _capture_basler_frame_for_save(zoom: float = 1.0, discard_frames: int = 0):
    """Capture one Basler frame; return (raw_image, preview_image_rgb).
    Optionally discard a few queued frames first to avoid stale images.
    """
    if _BASLER_INSTANCE is None:
        camera_model, open_error = _open_first_basler_camera()
        if open_error:
            raise RuntimeError(open_error)
        print(f"[BASLER START] Reconnected to Basler: {camera_model}")

    _restart_basler_grabbing_latest()

    discarded = 0
    for _ in range(max(0, int(discard_frames))):
        try:
            stale = _BASLER_INSTANCE.RetrieveResult(200)
            if stale.GrabSucceeded():
                discarded += 1
            stale.Release()
        except Exception:
            break
    if discarded:
        print(f"[BASLER START] Discarded {discarded} queued frame(s) before capture")

    # Give the camera a brief moment to deliver a fresh frame after queue flushing.
    time.sleep(0.3)

    grab_result = _BASLER_INSTANCE.RetrieveResult(5000)
    if not grab_result.GrabSucceeded():
        grab_result.Release()
        raise RuntimeError("Failed to capture Basler frame")

    import cv2
    raw_image = grab_result.GetArray()
    pixel_format = ""
    try:
        pixel_format = str(_BASLER_INSTANCE.PixelFormat.GetValue())
    except Exception:
        pixel_format = ""
    grab_result.Release()

    # Convert to RGB first (Bayer/Mono/BGR/RGB aware) so saved file is always color
    if len(raw_image.shape) == 2:
        fmt = pixel_format.lower()
        if "bayer" in fmt:
            if "rg" in fmt:
                image_rgb = cv2.cvtColor(raw_image, cv2.COLOR_BAYER_RG2RGB)
            elif "gr" in fmt:
                image_rgb = cv2.cvtColor(raw_image, cv2.COLOR_BAYER_GR2RGB)
            elif "gb" in fmt:
                image_rgb = cv2.cvtColor(raw_image, cv2.COLOR_BAYER_GB2RGB)
            elif "bg" in fmt:
                image_rgb = cv2.cvtColor(raw_image, cv2.COLOR_BAYER_BG2RGB)
            else:
                image_rgb = cv2.cvtColor(raw_image, cv2.COLOR_BAYER_RG2RGB)
        else:
            image_rgb = cv2.cvtColor(raw_image, cv2.COLOR_GRAY2RGB)
    elif len(raw_image.shape) == 3 and raw_image.shape[2] == 3:
        fmt = pixel_format.lower()
        if "rgb" in fmt:
            image_rgb = raw_image
        else:
            image_rgb = cv2.cvtColor(raw_image, cv2.COLOR_BGR2RGB)
    else:
        image_rgb = raw_image

    # Save image in BGR for OpenCV imwrite (always 3-channel color output)
    if len(image_rgb.shape) == 3 and image_rgb.shape[2] == 3:
        save_image = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
    else:
        save_image = image_rgb

    # Prepare preview image (RGB + optional zoom crop + resize)
    preview = image_rgb.copy()

    zoom = zoom or 1.0
    if zoom != 1.0:
        h, w = preview.shape[:2]
        crop_w = int(w / zoom)
        crop_h = int(h / zoom)
        x1 = (w - crop_w) // 2
        y1 = (h - crop_h) // 2
        preview = preview[y1:y1+crop_h, x1:x1+crop_w]

    h2, w2 = preview.shape[:2]
    if w2 > 640 or h2 > 480:
        preview = cv2.resize(preview, (640, 480), interpolation=cv2.INTER_LINEAR)

    try:
        if _BASLER_INSTANCE.IsGrabbing():
            _BASLER_INSTANCE.StopGrabbing()
    except Exception:
        pass

    return save_image, preview


def _move_tray_sequence_forward_once() -> str:
    """Run one forward step from tray_sequence.txt and advance TRAY_SEQUENCE_ROW."""
    global TRAY_SEQUENCE_ROW
    print(f"[TRAY FORWARD] Starting forward step from row {TRAY_SEQUENCE_ROW}")
    
    if not _TRAY_INSTANCE or not _TRAY_INSTANCE.is_connected():
        raise RuntimeError("Tray not connected")

    seq_file = os.path.join(os.path.dirname(__file__), 'tray_sequence.txt')
    if not os.path.exists(seq_file):
        raise RuntimeError("tray_sequence.txt not found")

    with open(seq_file, 'r') as f:
        lines = f.readlines()

    if TRAY_SEQUENCE_ROW >= len(lines):
        raise RuntimeError(f"Reached end of sequence (row {TRAY_SEQUENCE_ROW})")

    row_data = lines[TRAY_SEQUENCE_ROW].strip().split('\t')
    if len(row_data) < 2:
        raise RuntimeError(f"Invalid row format at row {TRAY_SEQUENCE_ROW}")

    try:
        x_delta = float(row_data[0])
        y_delta = float(row_data[1])
    except ValueError as e:
        raise RuntimeError(f"Could not parse coordinates at row {TRAY_SEQUENCE_ROW}") from e

    print(f"[TRAY FORWARD] Parsed row {TRAY_SEQUENCE_ROW}: X={x_delta}, Y={y_delta}")
    
    # Clear input buffer before starting
    if _TRAY_INSTANCE.ser:
        try:
            _TRAY_INSTANCE.ser.reset_input_buffer()
        except Exception:
            pass
    time.sleep(0.1)
    
    _TRAY_INSTANCE._send("G91")
    resp_g91 = _TRAY_INSTANCE._read_response(timeout=0.6)
    print(f"[TRAY FORWARD] G91 response: {repr(resp_g91)}")
    
    if x_delta != 0 or y_delta != 0:
        move_cmd = f"G0 X{x_delta} Y{y_delta} F3000"
        print(f"[TRAY FORWARD] Sending move: {move_cmd}")
        _TRAY_INSTANCE._send(move_cmd)
        resp_move = _TRAY_INSTANCE._read_response(timeout=1.2)
        print(f"[TRAY FORWARD] Move response: {repr(resp_move)}")
        
        print(f"[TRAY FORWARD] Sending M400 (wait for planner)")
        _TRAY_INSTANCE._send("M400")
        resp_m400 = _TRAY_INSTANCE._read_response(timeout=1.5)
        print(f"[TRAY FORWARD] M400 response: {repr(resp_m400)}")
    else:
        print(f"[TRAY FORWARD] No movement needed (X=0, Y=0)")
    
    _TRAY_INSTANCE._send("G90")
    resp_g90 = _TRAY_INSTANCE._read_response(timeout=0.6)
    print(f"[TRAY FORWARD] G90 response: {repr(resp_g90)}")
    
    # Position check after move to verify tray actually moved
    time.sleep(0.3)
    try:
        pos = _TRAY_INSTANCE.get_position(strict=False)
        print(f"[TRAY FORWARD] Position after move: X={pos[0]:.1f}, Y={pos[1]:.1f}, Z={pos[2]:.1f}")
    except Exception as e:
        print(f"[TRAY FORWARD] Could not verify position: {e}")

    used_row = TRAY_SEQUENCE_ROW
    TRAY_SEQUENCE_ROW += 1
    msg = f"Row {used_row}: X{x_delta:+.2f} Y{y_delta:+.2f}"
    print(f"[TRAY FORWARD] Complete. Row counter incremented to {TRAY_SEQUENCE_ROW}")
    return msg


def _move_tray_relative_and_wait(x_delta: float = 0.0, y_delta: float = 0.0, z_delta: float = 0.0, feedrate: int = 3000) -> None:
    """Execute a relative tray move while draining serial responses and restoring absolute mode."""
    if not _TRAY_INSTANCE or not _TRAY_INSTANCE.is_connected():
        raise RuntimeError("Tray not connected")

    if _TRAY_INSTANCE.ser:
        try:
            _TRAY_INSTANCE.ser.reset_input_buffer()
        except Exception:
            pass
    time.sleep(0.05)

    _TRAY_INSTANCE._send("G91")
    _TRAY_INSTANCE._read_response(timeout=0.6)

    move_parts = []
    if x_delta:
        move_parts.append(f"X{x_delta}")
    if y_delta:
        move_parts.append(f"Y{y_delta}")
    if z_delta:
        move_parts.append(f"Z{z_delta}")

    if move_parts:
        move_cmd = f"G0 {' '.join(move_parts)} F{feedrate}"
        _TRAY_INSTANCE._send(move_cmd)
        _TRAY_INSTANCE._read_response(timeout=1.2)
        _TRAY_INSTANCE._send("M400")
        _TRAY_INSTANCE._read_response(timeout=1.5)

    _TRAY_INSTANCE._send("G90")
    _TRAY_INSTANCE._read_response(timeout=0.6)


def _goto_basler_first_cup():
    """Move tray to the exact Basler first-cup coordinates used by UI check controls."""
    if not _TRAY_INSTANCE or not _TRAY_INSTANCE.is_connected():
        raise RuntimeError("Tray not connected")
    _TRAY_INSTANCE.goto(x=BASLER_FIRST_CUP_X, y=BASLER_FIRST_CUP_Y, z=TRAY_WORK_Z)


def _ensure_basler_first_cup(tolerance_mm: float = 0.75, retries: int = 2):
    """Move to Basler first cup and verify actual arrival, retrying if necessary."""
    last_pos = None
    last_error = None

    for attempt in range(retries):
        _goto_basler_first_cup()
        try:
            _TRAY_INSTANCE._send("M400")
            _TRAY_INSTANCE._read_response(timeout=15)
        except Exception:
            pass

        time.sleep(0.25)
        try:
            last_pos = _TRAY_INSTANCE.get_position(strict=True)
            dx = abs(last_pos[0] - BASLER_FIRST_CUP_X)
            dy = abs(last_pos[1] - BASLER_FIRST_CUP_Y)
            dz = abs(last_pos[2] - TRAY_WORK_Z)
            print(f"[BASLER START] First-cup verify attempt {attempt + 1}: X={last_pos[0]:.2f}, Y={last_pos[1]:.2f}, Z={last_pos[2]:.2f}")
            if dx <= tolerance_mm and dy <= tolerance_mm and dz <= tolerance_mm:
                return
            last_error = f"verify mismatch dx={dx:.2f}, dy={dy:.2f}, dz={dz:.2f}"
        except Exception as e:
            last_error = str(e)

    if last_pos is not None:
        raise RuntimeError(
            f"Could not verify Basler first cup after {retries} attempt(s). "
            f"Last position: X={last_pos[0]:.2f}, Y={last_pos[1]:.2f}, Z={last_pos[2]:.2f}. Last error: {last_error}"
        )
    raise RuntimeError(f"Could not verify Basler first cup after {retries} attempt(s): {last_error}")


@app.callback(
    Output("tray-status", "children", allow_duplicate=True),
    Output("basler-photo-frame", "children", allow_duplicate=True),
    Input("btn-start-basler", "n_clicks"),
    State("store-basler", "data"),
    State("store-sample-type", "data"),
    State("store-video-zoom", "data"),
    State("x550-combo-count", "value"),
    prevent_initial_call=True,
)
def start_basler_sequence(_n_clicks=None, basler_data=None, sample_type=None, zoom=1.0, basler_count=None,
                             override_test_numbers=None, override_save_dir=None):
    """Start Basler sequence:
    1) move to Basler first cup
    2) capture + save JPEG
    3) filename = counter + date + sample
    4) forward tray by tray_sequence row
    5) repeat for total captures (default = x550-combo-count, or len(override_test_numbers))
    
    Optional parameters:
    - override_test_numbers: list of 3 test numbers to use instead of auto-generating
    - override_save_dir: directory to save to instead of SAVED_FOLDER
    """
    import cv2

    global BASLER_FIRST_CUP_X, BASLER_FIRST_CUP_Y, TRAY_WORK_Z, TRAY_SEQUENCE_ROW, TRAY_SEQUENCE_RUNNING

    # If called as a callback, log it
    if _n_clicks is not None:
        log_button_click("Start basler")

    if not _TRAY_INSTANCE or not _TRAY_INSTANCE.is_connected():
        print("[BASLER START] ERROR: Tray not connected")
        return "[ERROR] Tray not connected", dash.no_update
    if not basler_data or not basler_data.get("basler_connected"):
        print("[BASLER START] ERROR: Basler camera not connected")
        return "[ERROR] Basler camera not connected", dash.no_update
    sample_value = str(sample_type).strip() if sample_type is not None else ""
    if (not sample_value) or (sample_value.lower() in {"not specified", "other"}):
        msg = "[ERROR] Sample type is missing. Please select a sample type before Start basler"
        print(f"[BASLER START] {msg}")
        return msg, dash.no_update

    print(f"[BASLER START] All pre-checks passed. Sample type: {sample_value}")
    save_dir = override_save_dir if override_save_dir else (SAVED_FOLDER if SAVED_FOLDER else os.path.dirname(__file__))
    try:
        os.makedirs(save_dir, exist_ok=True)
    except Exception as e:
        print(f"[BASLER START] ERROR: Could not create save folder: {e}")
        return f"[ERROR] Could not create save folder: {e}", dash.no_update

    safe_sample = sample_value.lower().replace(" ", "-").replace("/", "-").replace("\\", "-")
    today = datetime.datetime.now().strftime("%Y_%m_%d")
    TRAY_SEQUENCE_ROW = 2
    print(f"[BASLER START] Moving to first cup: X={BASLER_FIRST_CUP_X}, Y={BASLER_FIRST_CUP_Y}, Z={TRAY_WORK_Z}")

    # Step 1: move to first Basler cup
    try:
        _ensure_basler_first_cup()
        time.sleep(3)
        print(f"[BASLER START] First cup move complete and settled")
    except Exception as e:
        print(f"[BASLER START] ERROR during first cup move: {e}")
        import traceback
        traceback.print_exc()
        return f"[ERROR] Could not move to Basler first cup: {e}", dash.no_update

    saved_files = []
    last_preview = dash.no_update

    if override_test_numbers is not None:
        total_shots = len(override_test_numbers)
        if total_shots < 1:
            return "[ERROR] No override test numbers provided", dash.no_update
    else:
        try:
            total_shots = int(basler_count) if basler_count is not None else 3
        except (TypeError, ValueError):
            total_shots = 3
        if total_shots < 1:
            total_shots = 3

    try:
        TRAY_SEQUENCE_RUNNING = True
        for shot_idx in range(total_shots):
            print(f"[BASLER START] Shot {shot_idx + 1}/{total_shots}: Getting test number and capturing...")
            # Use provided test numbers or auto-generate
            if override_test_numbers and shot_idx < len(override_test_numbers):
                test_num = override_test_numbers[shot_idx]
                print(f"[BASLER START] Using override test number: {test_num:06d}")
            else:
                test_num = get_next_test_number()
            file_name = f"{test_num:06d}_{today}_{safe_sample}.jpg"
            file_path = os.path.join(save_dir, file_name)

            raw_image, preview_rgb = _capture_basler_frame_for_save(zoom=zoom, discard_frames=8)
            if not cv2.imwrite(file_path, raw_image, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                raise RuntimeError(f"Failed to write JPEG: {file_name}")
            saved_files.append(file_name)
            print(f"[BASLER START] Shot {shot_idx + 1}/{total_shots}: Saved {file_name}")

            _, preview_buf = cv2.imencode('.jpg', preview_rgb, [cv2.IMWRITE_JPEG_QUALITY, 90])
            preview_base64 = base64.b64encode(preview_buf).decode()
            last_preview = html.Img(
                src=f"data:image/jpeg;base64,{preview_base64}",
                id="basler-photo-img",
                style={"width": "100%", "border": "2px solid #9e9e9e", "backgroundColor": "#f2f2f2"}
            )

            if shot_idx < total_shots - 1:
                try:
                    move_msg = _move_tray_sequence_forward_once()
                    print(f"[BASLER START] Forward: {move_msg}")
                except Exception as e:
                    print(f"[BASLER START] ERROR during forward step: {e}")
                    import traceback
                    traceback.print_exc()
                    raise

        return f"[OK] Start basler complete. Saved: {', '.join(saved_files)}", last_preview

    except Exception as e:
        print(f"[BASLER START] Error: {e}")
        import traceback
        traceback.print_exc()
        return f"[ERROR] Start basler failed: {e}", last_preview
    finally:
        TRAY_SEQUENCE_RUNNING = False


@app.callback(
    Output("tray-status", "children"),
    Output("tray-port", "children"),
    Output("system-status", "children"),
    Input("store-connection", "data"),
)
def render_status(data):
    if not data:
        return (
            dbc.Badge("Not connected", color="secondary"),
            "",
            dbc.Alert("Click 'Connect to Tray' to begin.", color="secondary"),
        )

    tray_ok = bool(data.get("tray_connected"))

    tray_badge = dbc.Badge("Connected" if tray_ok else "Disconnected",
                           color="success" if tray_ok else "danger")

    tray_port_txt = f"Port: {data.get('tray_port')}" if tray_ok else (data.get("tray_port") or "")

    if data.get("ready"):
        sys_msg = dbc.Alert("Tray ready [OK]", color="success")
    else:
        sys_msg = dbc.Alert(data.get("error") or "Tray not ready", color="danger")

    return tray_badge, tray_port_txt, sys_msg

@app.callback(
    Output("btn-first", "disabled"),
    Output("btn-last", "disabled"),
    Output("btn-edit-first", "disabled"),
    Output("btn-save-first", "disabled"),
    Output("btn-first-basler", "disabled"),
    Output("btn-last-basler", "disabled"),
    Output("btn-edit-first-basler", "disabled"),
    Output("btn-save-first-basler", "disabled"),
    Output("btn-home", "disabled"),
    Output("btn-forward-sequence", "disabled"),
    Output("btn-reset-sequence", "disabled"),
    Output("btn-position-tray", "disabled"),
    Input("store-connection", "data"),
)
def enable_tray_buttons(data):
    """Enable tray buttons when tray is connected"""
    if not data or not data.get("tray_connected"):
        return True, True, True, True, True, True, True, True, True, True, True, True
    return False, False, False, False, False, False, False, False, False, False, False, False

@app.callback(
    Output("x550-status", "children"),
    Output("x550-url", "children"),
    Output("x550-heartbeat-timer", "interval"),
    Output("x550-screenshot-timer", "disabled"),
    Input("store-x550", "data"),
)
def render_x550_status(data):
    if not data:
        return (
            dbc.Badge("Not connected", color="secondary"),
            "",
            3000,  # Keep heartbeat disabled if not connected
            True,  # Disable screenshot timer
        )

    x550_ok = bool(data.get("x550_connected"))

    x550_badge = dbc.Badge("Connected" if x550_ok else "Disconnected",
                           color="success" if x550_ok else "danger")

    x550_url_txt = f"URL: {data.get('x550_url')}" if x550_ok else (data.get("error") or "")

    return x550_badge, x550_url_txt, 3000, True  # Keep screenshot timer disabled


@app.callback(
    Output("basler-status", "children"),
    Output("basler-info", "children"),
    Input("store-basler", "data"),
)
def render_basler_status(data):
    if not data:
        return (
            dbc.Badge("Not connected", color="secondary"),
            "",
        )

    basler_ok = bool(data.get("basler_connected"))

    basler_badge = dbc.Badge("Connected" if basler_ok else "Disconnected",
                            color="success" if basler_ok else "danger")

    basler_info_txt = data.get("basler_info") if basler_ok else (data.get("error") or "")

    return basler_badge, basler_info_txt


@app.callback(
    Output("x550-quick-test-status", "children"),
    Input("btn-x550-quick-test", "n_clicks"),
    State("store-x550", "data"),
    prevent_initial_call=True,
)
def x550_quick_test(_n_clicks, x550_data):
    """Quick test: Mining mode, 1 shot"""
    if not x550_data or not x550_data.get("x550_connected"):
        log_button_click("1 Mining Test")
        return "[ERROR] X550 not connected"
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        log_button_click("1 Mining Test")
        return "[ERROR] Missing base URL"
    
    try:
        app_mode = "Mining"
        
        # Call test endpoint with proper format per API docs
        # Note: API tests do NOT save on device - device only saves when using physical trigger
        test_url = f"{base_url}/api/v2/test/final"
        
        print(f"[QUICK TEST] Running Mining test at {test_url}?mode={app_mode}")
        # Per API docs: POST with empty body and mode as query param
        test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)
        
        if not test_r.ok:
            error_text = test_r.text[:500] if test_r.text else "No error message"
            print(f"[QUICK TEST] Failed - HTTP {test_r.status_code}: {error_text}")
            log_button_click("1 Mining Test")
            return f"[ERROR] Test failed - HTTP {test_r.status_code}"
        
        try:
            result = test_r.json()
            test_num = get_next_test_number()
            # Log with test number as soon as we have it
            log_button_click("1 Mining Test", test_number=f"{test_num:06d}")
            
            # Save spectra to CSV files locally
            if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                now = datetime.datetime.now()
                timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"
                
                # Process each spectrum and save as CSV
                if "spectra" in result:
                    for spec in result["spectra"]:
                        beam_name = spec.get("beamName", "Unknown")
                        spectrum_data = spec.get("data", [])
                        
                        # Get calibration info
                        energy_offset = spec.get("energyOffset", 0)
                        energy_slope = spec.get("energySlope", 1)
                        
                        # Generate CSV filename
                        csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}.csv"
                        csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)
                        
                        # Write CSV file with header and calibrated energy values
                        with open(csv_filepath, 'w') as f:
                            f.write("Energy (keV),Intensity (cps)\n")
                            for bin_idx, intensity in enumerate(spectrum_data):
                                energy = energy_offset + (bin_idx * energy_slope)
                                f.write(f"{energy},{intensity}\n")
                        
                        print(f"[QUICK TEST] Saved spectrum to {csv_filepath}")
                    
                    # Save one screenshot per test
                    screenshot_name = f"{test_num:06d}_{timestamp}_Mining.png"
                    screenshot_path = os.path.join(SAVED_FOLDER, screenshot_name)
                    save_x550_screenshot(base_url, screenshot_path)
            
            chem = result.get("testData", {}).get("chemistry", [])
            elements = ", ".join([c.get("symbol", f"Z{c.get('atomicNumber')}") for c in chem[:5]])
            print(f"[QUICK TEST] Test completed - detected: {elements}")
            return f"[OK] Test complete - {elements}"
        except:
            print(f"[QUICK TEST] Test completed successfully")
            return "[OK] Mining test complete"

    except requests.exceptions.Timeout:
        return "[ERROR] Test timeout (>60s)"
    except Exception as e:
        print(f"[QUICK TEST] Error: {e}")
        import traceback
        traceback.print_exc()
        return f"[ERROR] Test failed: {type(e).__name__}"


@app.callback(
    Output("x550-quick-soil-test-status", "children"),
    Input("btn-x550-quick-soil-test", "n_clicks"),
    State("store-x550", "data"),
    prevent_initial_call=True,
)
def x550_quick_soil_test(_n_clicks, x550_data):
    """Quick test: Soil mode, 1 shot"""
    if not x550_data or not x550_data.get("x550_connected"):
        log_button_click("1 Soil Test")
        return "[ERROR] X550 not connected"
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        log_button_click("1 Soil Test")
        return "[ERROR] Missing base URL"
    
    try:
        app_mode = "Soil"
        
        # Call test endpoint with proper format per API docs
        # Note: API tests do NOT save on device - device only saves when using physical trigger
        test_url = f"{base_url}/api/v2/test/final"
        
        print(f"[QUICK TEST SOIL] Running Soil test at {test_url}?mode={app_mode}")
        print(f"[QUICK TEST SOIL] Note: API tests are not saved on device, only in local CSV files")
        
        # Per API docs: POST with empty body and mode as query param
        test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)
        
        if not test_r.ok:
            error_text = test_r.text[:500] if test_r.text else "No error message"
            print(f"[QUICK TEST SOIL] Failed - HTTP {test_r.status_code}: {error_text}")
            log_button_click("1 Soil Test")
            return f"[ERROR] Test failed - HTTP {test_r.status_code}"
        
        try:
            result = test_r.json()
            test_num = get_next_test_number()
            # Log with test number as soon as we have it
            log_button_click("1 Soil Test", test_number=f"{test_num:06d}")
            
            # Save spectra to CSV files locally
            if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                now = datetime.datetime.now()
                timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"
                
                # Process each spectrum and save as CSV
                if "spectra" in result:
                    for spec in result["spectra"]:
                        beam_name = spec.get("beamName", "Unknown")
                        spectrum_data = spec.get("data", [])
                        
                        # Get calibration info
                        energy_offset = spec.get("energyOffset", 0)
                        energy_slope = spec.get("energySlope", 1)
                        
                        # Generate CSV filename
                        csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}.csv"
                        csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)
                        
                        # Write CSV file with header and calibrated energy values
                        with open(csv_filepath, 'w') as f:
                            f.write("Energy (keV),Intensity (cps)\n")
                            for bin_idx, intensity in enumerate(spectrum_data):
                                energy = energy_offset + (bin_idx * energy_slope)
                                f.write(f"{energy},{intensity}\n")
                        
                        print(f"[QUICK TEST SOIL] Saved spectrum to {csv_filepath}")
                    
                    # Save one screenshot per test
                    screenshot_name = f"{test_num:06d}_{timestamp}_Soil.png"
                    screenshot_path = os.path.join(SAVED_FOLDER, screenshot_name)
                    save_x550_screenshot(base_url, screenshot_path)
            
            chem = result.get("testData", {}).get("chemistry", [])
            elements = ", ".join([c.get("symbol", f"Z{c.get('atomicNumber')}") for c in chem[:5]])
            print(f"[QUICK TEST SOIL] Test completed - detected: {elements}")
            return f"[OK] Test complete - {elements}"
        except:
            print(f"[QUICK TEST SOIL] Test completed successfully")
            return "[OK] Soil test complete"

    except requests.exceptions.Timeout:
        return "[ERROR] Test timeout (>60s)"
    except Exception as e:
        print(f"[QUICK TEST SOIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return f"[ERROR] Test failed: {type(e).__name__}"


@app.callback(
    Output("x550-quick-combo-test-2-status", "children"),
    Input("btn-x550-quick-combo-test-2", "n_clicks"),
    State("store-x550", "data"),
    prevent_initial_call=True,
)
def x550_quick_combo_test_2(_n_clicks, x550_data):
    """Combined test with chemistry export: 1 Mining test then 1 Soil test - both use same test number"""
    if not x550_data or not x550_data.get("x550_connected"):
        log_button_click("Combo Test 2")
        return "[ERROR] X550 not connected"
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        log_button_click("Combo Test 2")
        return "[ERROR] Missing base URL"
    
    # Get test number once for the entire combo
    test_num = get_next_test_number()
    log_button_click("Combo Test 2", test_number=f"{test_num:06d}")
    
    results = []
    chemistry_rows = []
    
    # Execute Mining test first
    try:
        app_mode = "Mining"
        test_url = f"{base_url}/api/v2/test/final"
        
        print(f"[COMBO TEST 2] Running Mining test - {test_num:06d}")
        test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)
        
        if test_r.ok:
            try:
                mining_result = test_r.json()
                
                # Save Mining spectra
                if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                    now = datetime.datetime.now()
                    timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"
                    
                    if "spectra" in mining_result:
                        shot_num = 1
                        for spec in mining_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)
                            livetime = spec.get("liveTime", "N/A")
                            livetimemultiplier = spec.get("liveTimeMultiplier", "N/A")
                            
                            print(f"[COMBO TEST 2] Mining Shot {shot_num}: liveTime={livetime}, liveTimeMultiplier={livetimemultiplier}")
                            shot_num += 1
                            
                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}.csv"
                            csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)
                            
                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (cps)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    f.write(f"{energy},{intensity}\n")
                    
                    # Extract chemistry data for Mining
                    if "testData" in mining_result and "chemistry" in mining_result["testData"]:
                        chem = mining_result["testData"]["chemistry"]
                        test_data = mining_result["testData"]
                        date_str = now.strftime("%Y-%m-%d %H:%M:%S")
                        serial = mining_result.get("serialNumber", "X550-Unknown")
                        chemistry_rows.append({
                            "Date": date_str,
                            "Test #": test_num,
                            "Serial #": serial,
                            "Mode": "Mining",
                            "Grade1": test_data.get("firstGradeMatch", ""),
                            "Grade2": test_data.get("secondGradeMatch", ""),
                            "Grade3": test_data.get("thirdGradeMatch", ""),
                            "chemistry": chem
                        })
                        print(f"[COMBO TEST 2] Mining chemistry extracted: {len(chem)} elements")
                        if len(chem) > 0:
                            print(f"[COMBO TEST 2] First element sample: {chem[0]}")
                    else:
                        print(f"[COMBO TEST 2] WARNING: No chemistry in Mining result. Keys: {mining_result.keys()}")
                        if "testData" in mining_result:
                            print(f"[COMBO TEST 2] testData keys: {mining_result['testData'].keys()}")
                
                results.append(f"Mining: OK")
                print(f"[COMBO TEST 2] Mining test completed - {test_num:06d}")
            except Exception as e:
                print(f"[COMBO TEST 2] Mining test error: {e}")
                results.append("Mining: failed")
        else:
            results.append("Mining: failed")
    except Exception as e:
        print(f"[COMBO TEST 2] Mining test error: {e}")
        results.append("Mining: failed")
    
    # Execute Soil test second (same test number)
    try:
        app_mode = "Soil"
        test_url = f"{base_url}/api/v2/test/final"
        
        print(f"[COMBO TEST 2] Running Soil test - {test_num:06d}")
        test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)
        
        if test_r.ok:
            try:
                soil_result = test_r.json()
                
                # Save Soil spectra (same test number, new timestamp)
                if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                    now = datetime.datetime.now()
                    timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"
                    
                    if "spectra" in soil_result:
                        shot_num = 1
                        for spec in soil_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)
                            livetime = spec.get("liveTime", "N/A")
                            livetimemultiplier = spec.get("liveTimeMultiplier", "N/A")
                            
                            print(f"[COMBO TEST 2] Soil Shot {shot_num}: liveTime={livetime}, liveTimeMultiplier={livetimemultiplier}")
                            shot_num += 1
                            
                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}.csv"
                            csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)
                            
                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (cps)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    f.write(f"{energy},{intensity}\n")
                    
                    # Extract chemistry data for Soil
                    if "testData" in soil_result and "chemistry" in soil_result["testData"]:
                        chem = soil_result["testData"]["chemistry"]
                        test_data = soil_result["testData"]
                        date_str = now.strftime("%Y-%m-%d %H:%M:%S")
                        serial = soil_result.get("serialNumber", "X550-Unknown")
                        chemistry_rows.append({
                            "Date": date_str,
                            "Test #": test_num,
                            "Serial #": serial,
                            "Mode": "Soil",
                            "Grade1": test_data.get("firstGradeMatch", ""),
                            "Grade2": test_data.get("secondGradeMatch", ""),
                            "Grade3": test_data.get("thirdGradeMatch", ""),
                            "chemistry": chem
                        })
                        print(f"[COMBO TEST 2] Soil chemistry extracted: {len(chem)} elements")
                        if len(chem) > 0:
                            print(f"[COMBO TEST 2] First element sample: {chem[0]}")
                    else:
                        print(f"[COMBO TEST 2] WARNING: No chemistry in Soil result. Keys: {soil_result.keys()}")
                        if "testData" in soil_result:
                            print(f"[COMBO TEST 2] testData keys: {soil_result['testData'].keys()}")
                
                results.append(f"Soil: OK")
                print(f"[COMBO TEST 2] Soil test completed - {test_num:06d}")
            except Exception as e:
                print(f"[COMBO TEST 2] Soil test error: {e}")
                results.append("Soil: failed")
        else:
            results.append("Soil: failed")
    except Exception as e:
        print(f"[COMBO TEST 2] Soil test error: {e}")
        results.append("Soil: failed")
    
    # Save chemistry data to CSV
    if chemistry_rows and SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
        try:
            # Create timestamp for chemistry filename
            chem_now = datetime.datetime.now()
            chem_timestamp = chem_now.strftime("%Y_%m_%d_%H%M%S") + f"{int(chem_now.microsecond / 10000):02d}"
            chemistry_csv = os.path.join(SAVED_FOLDER, f"{test_num:06d}_{chem_timestamp}_chemistry.csv")
            
            # Atomic number to element symbol mapping
            ELEMENT_SYMBOLS = {
                1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O", 9: "F", 10: "Ne",
                11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P", 16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca",
                21: "Sc", 22: "Ti", 23: "V", 24: "Cr", 25: "Mn", 26: "Fe", 27: "Co", 28: "Ni", 29: "Cu", 30: "Zn",
                31: "Ga", 32: "Ge", 33: "As", 34: "Se", 35: "Br", 36: "Kr", 37: "Rb", 38: "Sr", 39: "Y", 40: "Zr",
                41: "Nb", 42: "Mo", 43: "Tc", 44: "Ru", 45: "Rh", 46: "Pd", 47: "Ag", 48: "Cd", 49: "In", 50: "Sn",
                51: "Sb", 52: "Te", 53: "I", 54: "Xe", 55: "Cs", 56: "Ba", 57: "La", 58: "Ce", 59: "Pr", 60: "Nd",
                61: "Pm", 62: "Sm", 63: "Eu", 64: "Gd", 65: "Tb", 66: "Dy", 67: "Ho", 68: "Er", 69: "Tm", 70: "Yb",
                71: "Lu", 72: "Hf", 73: "Ta", 74: "W", 75: "Re", 76: "Os", 77: "Ir", 78: "Pt", 79: "Au", 80: "Hg",
                81: "Tl", 82: "Pb", 83: "Bi", 84: "Po", 85: "At", 86: "Rn", 87: "Fr", 88: "Ra", 89: "Ac", 90: "Th",
                91: "Pa", 92: "U", 93: "Np", 94: "Pu", 95: "Am", 96: "Cm", 97: "Bk", 98: "Cf", 99: "Es", 100: "Fm"
            }
            
            # Build CSV with all elements
            import csv
            with open(chemistry_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                
                # Write header
                header = ["Date", "Test #", "Serial #", "Grade Match #1", "Grade Match #2", "Grade Match #3", "Mode", "AVG Flag"]
                
                # Get all element atomic numbers from both tests
                all_atomic_numbers = set()
                for row in chemistry_rows:
                    if "chemistry" in row:
                        for elem_data in row["chemistry"]:
                            all_atomic_numbers.add(elem_data.get("atomicNumber", 0))
                
                # Sort by atomic number and add element columns
                sorted_atomic_numbers = sorted(all_atomic_numbers)
                for atomic_num in sorted_atomic_numbers:
                    elem_symbol = ELEMENT_SYMBOLS.get(atomic_num, f"Z{atomic_num}")
                    header.extend([elem_symbol, f"{elem_symbol} +/-"])
                
                writer.writerow(header)
                
                # Write data rows
                for row in chemistry_rows:
                    data_row = [
                        row["Date"],
                        row["Test #"],
                        row["Serial #"],
                        row.get("Grade1", ""),
                        row.get("Grade2", ""),
                        row.get("Grade3", ""),
                        row["Mode"],
                        ""  # AVG Flag
                    ]
                    
                    # Create dict of element values keyed by atomic number
                    elem_values = {}
                    if "chemistry" in row:
                        for elem_data in row["chemistry"]:
                            atomic_num = elem_data.get("atomicNumber", 0)
                            percent = elem_data.get("percent", "")
                            uncertainty = elem_data.get("uncertainty", "")
                            flags = elem_data.get("flags", 0)
                            
                            # Format value with flags (ND for below detection, etc.)
                            value_str = ""
                            error_str = ""
                            
                            # Check if below LOD (Less than Limit of Detection)
                            if flags & 8:  # TYPE_LESS_LOD
                                value_str = "ND"
                                error_str = f"< {percent:.2f}" if isinstance(percent, (int, float)) else ""
                            elif isinstance(percent, (int, float)) and isinstance(uncertainty, (int, float)):
                                value_str = f"{percent:.2f}"
                                error_str = f"{uncertainty:.2f}"
                            
                            elem_values[atomic_num] = (value_str, error_str)
                    
                    # Add element values in order
                    for atomic_num in sorted_atomic_numbers:
                        if atomic_num in elem_values:
                            data_row.extend([elem_values[atomic_num][0], elem_values[atomic_num][1]])
                        else:
                            data_row.extend(["", ""])
                    
                    writer.writerow(data_row)
            
            print(f"[COMBO TEST 2] Chemistry data saved to {chemistry_csv}")
        except Exception as e:
            print(f"[COMBO TEST 2] Error saving chemistry data: {e}")
            import traceback
            traceback.print_exc()
    
    return f"[OK] Combo Test 2 completed - {test_num:06d}: " + ", ".join(results)


@app.callback(
    Output("x550-quick-combo-test-3-status", "children"),
    Input("btn-x550-quick-combo-test-3", "n_clicks"),
    State("store-x550", "data"),
    prevent_initial_call=True,
)
def x550_quick_combo_test_3(_n_clicks, x550_data):
    """Combined test with CPS conversion: 1 Mining test then 1 Soil test - both use same test number"""
    if not x550_data or not x550_data.get("x550_connected"):
        log_button_click("Combo Test 3")
        return "[ERROR] X550 not connected"
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        log_button_click("Combo Test 3")
        return "[ERROR] Missing base URL"
    
    # Get test number once for the entire combo
    test_num = get_next_test_number()
    log_button_click("Combo Test 3", test_number=f"{test_num:06d}")
    
    results = []
    chemistry_rows = []
    
    # Execute Mining test first
    try:
        app_mode = "Mining"
        test_url = f"{base_url}/api/v2/test/final"
        
        print(f"[COMBO TEST 3] Running Mining test - {test_num:06d}")
        test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)
        
        if test_r.ok:
            try:
                mining_result = test_r.json()
                
                # Save Mining spectra with CPS conversion
                if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                    now = datetime.datetime.now()
                    timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"
                    
                    if "spectra" in mining_result:
                        shot_num = 1
                        for spec in mining_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)
                            livetime = spec.get("liveTime", "N/A")
                            livetimemultiplier = spec.get("liveTimeMultiplier", "N/A")
                            
                            print(f"[COMBO TEST 3] Mining Shot {shot_num}: liveTime={livetime}, liveTimeMultiplier={livetimemultiplier}")
                            
                            # Calculate CPS conversion
                            total_count = sum(spectrum_data) if spectrum_data else 0
                            cps_conversion = 1.0
                            if isinstance(livetime, (int, float)) and isinstance(livetimemultiplier, (int, float)) and livetime > 0:
                                cps_conversion = (livetimemultiplier / livetime)
                                corrected_counts = total_count * livetimemultiplier / livetime
                                print(f"[COMBO TEST 3] Mining Shot {shot_num}: Total counts={total_count}, Corrected CPS={corrected_counts:.2f}")
                            
                            shot_num += 1
                            
                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}_CPS.csv"
                            csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)
                            
                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (CPS)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    intensity_cps = intensity * cps_conversion
                                    f.write(f"{energy},{intensity_cps}\n")
                    
                    # Extract chemistry data for Mining
                    if "testData" in mining_result and "chemistry" in mining_result["testData"]:
                        chem = mining_result["testData"]["chemistry"]
                        test_data = mining_result["testData"]
                        date_str = now.strftime("%Y-%m-%d %H:%M:%S")
                        serial = mining_result.get("serialNumber", "X550-Unknown")
                        chemistry_rows.append({
                            "Date": date_str,
                            "Test #": test_num,
                            "Serial #": serial,
                            "Mode": "Mining",
                            "Grade1": test_data.get("firstGradeMatch", ""),
                            "Grade2": test_data.get("secondGradeMatch", ""),
                            "Grade3": test_data.get("thirdGradeMatch", ""),
                            "chemistry": chem
                        })
                        print(f"[COMBO TEST 3] Mining chemistry extracted: {len(chem)} elements")
                        if len(chem) > 0:
                            print(f"[COMBO TEST 3] First element sample: {chem[0]}")
                    else:
                        print(f"[COMBO TEST 3] WARNING: No chemistry in Mining result. Keys: {mining_result.keys()}")
                        if "testData" in mining_result:
                            print(f"[COMBO TEST 3] testData keys: {mining_result['testData'].keys()}")
                
                results.append(f"Mining: OK")
                print(f"[COMBO TEST 3] Mining test completed - {test_num:06d}")
            except Exception as e:
                print(f"[COMBO TEST 3] Mining test error: {e}")
                results.append("Mining: failed")
        else:
            results.append("Mining: failed")
    except Exception as e:
        print(f"[COMBO TEST 3] Mining test error: {e}")
        results.append("Mining: failed")
    
    # Execute Soil test second (same test number)
    try:
        app_mode = "Soil"
        test_url = f"{base_url}/api/v2/test/final"
        
        print(f"[COMBO TEST 3] Running Soil test - {test_num:06d}")
        test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)
        
        if test_r.ok:
            try:
                soil_result = test_r.json()
                
                # Save Soil spectra with CPS conversion (same test number, new timestamp)
                if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                    now = datetime.datetime.now()
                    timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"
                    
                    if "spectra" in soil_result:
                        shot_num = 1
                        for spec in soil_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)
                            livetime = spec.get("liveTime", "N/A")
                            livetimemultiplier = spec.get("liveTimeMultiplier", "N/A")
                            
                            print(f"[COMBO TEST 3] Soil Shot {shot_num}: liveTime={livetime}, liveTimeMultiplier={livetimemultiplier}")
                            
                            # Calculate CPS conversion
                            total_count = sum(spectrum_data) if spectrum_data else 0
                            cps_conversion = 1.0
                            if isinstance(livetime, (int, float)) and isinstance(livetimemultiplier, (int, float)) and livetime > 0:
                                cps_conversion = (livetimemultiplier / livetime)
                                corrected_counts = total_count * livetimemultiplier / livetime
                                print(f"[COMBO TEST 3] Soil Shot {shot_num}: Total counts={total_count}, Corrected CPS={corrected_counts:.2f}")
                            
                            shot_num += 1
                            
                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}_CPS.csv"
                            csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)
                            
                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (CPS)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    intensity_cps = intensity * cps_conversion
                                    f.write(f"{energy},{intensity_cps}\n")
                    
                    # Extract chemistry data for Soil
                    if "testData" in soil_result and "chemistry" in soil_result["testData"]:
                        chem = soil_result["testData"]["chemistry"]
                        test_data = soil_result["testData"]
                        date_str = now.strftime("%Y-%m-%d %H:%M:%S")
                        serial = soil_result.get("serialNumber", "X550-Unknown")
                        chemistry_rows.append({
                            "Date": date_str,
                            "Test #": test_num,
                            "Serial #": serial,
                            "Mode": "Soil",
                            "Grade1": test_data.get("firstGradeMatch", ""),
                            "Grade2": test_data.get("secondGradeMatch", ""),
                            "Grade3": test_data.get("thirdGradeMatch", ""),
                            "chemistry": chem
                        })
                        print(f"[COMBO TEST 3] Soil chemistry extracted: {len(chem)} elements")
                        if len(chem) > 0:
                            print(f"[COMBO TEST 3] First element sample: {chem[0]}")
                    else:
                        print(f"[COMBO TEST 3] WARNING: No chemistry in Soil result. Keys: {soil_result.keys()}")
                        if "testData" in soil_result:
                            print(f"[COMBO TEST 3] testData keys: {soil_result['testData'].keys()}")
                
                results.append(f"Soil: OK")
                print(f"[COMBO TEST 3] Soil test completed - {test_num:06d}")
            except Exception as e:
                print(f"[COMBO TEST 3] Soil test error: {e}")
                results.append("Soil: failed")
        else:
            results.append("Soil: failed")
    except Exception as e:
        print(f"[COMBO TEST 3] Soil test error: {e}")
        results.append("Soil: failed")
    
    # Save chemistry data to CSV (same as combo test 2)
    if chemistry_rows and SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
        try:
            # Create timestamp for chemistry filename
            chem_now = datetime.datetime.now()
            chem_timestamp = chem_now.strftime("%Y_%m_%d_%H%M%S") + f"{int(chem_now.microsecond / 10000):02d}"
            chemistry_csv = os.path.join(SAVED_FOLDER, f"{test_num:06d}_{chem_timestamp}_chemistry.csv")
            
            # Atomic number to element symbol mapping
            ELEMENT_SYMBOLS = {
                1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O", 9: "F", 10: "Ne",
                11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P", 16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca",
                21: "Sc", 22: "Ti", 23: "V", 24: "Cr", 25: "Mn", 26: "Fe", 27: "Co", 28: "Ni", 29: "Cu", 30: "Zn",
                31: "Ga", 32: "Ge", 33: "As", 34: "Se", 35: "Br", 36: "Kr", 37: "Rb", 38: "Sr", 39: "Y", 40: "Zr",
                41: "Nb", 42: "Mo", 43: "Tc", 44: "Ru", 45: "Rh", 46: "Pd", 47: "Ag", 48: "Cd", 49: "In", 50: "Sn",
                51: "Sb", 52: "Te", 53: "I", 54: "Xe", 55: "Cs", 56: "Ba", 57: "La", 58: "Ce", 59: "Pr", 60: "Nd",
                61: "Pm", 62: "Sm", 63: "Eu", 64: "Gd", 65: "Tb", 66: "Dy", 67: "Ho", 68: "Er", 69: "Tm", 70: "Yb",
                71: "Lu", 72: "Hf", 73: "Ta", 74: "W", 75: "Re", 76: "Os", 77: "Ir", 78: "Pt", 79: "Au", 80: "Hg",
                81: "Tl", 82: "Pb", 83: "Bi", 84: "Po", 85: "At", 86: "Rn", 87: "Fr", 88: "Ra", 89: "Ac", 90: "Th",
                91: "Pa", 92: "U", 93: "Np", 94: "Pu", 95: "Am", 96: "Cm", 97: "Bk", 98: "Cf", 99: "Es", 100: "Fm"
            }
            
            # Build CSV with all elements
            import csv
            with open(chemistry_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                
                # Write header
                header = ["Date", "Test #", "Serial #", "Grade Match #1", "Grade Match #2", "Grade Match #3", "Mode", "AVG Flag"]
                
                # Get all element atomic numbers from both tests
                all_atomic_numbers = set()
                for row in chemistry_rows:
                    if "chemistry" in row:
                        for elem_data in row["chemistry"]:
                            all_atomic_numbers.add(elem_data.get("atomicNumber", 0))
                
                # Sort by atomic number and add element columns
                sorted_atomic_numbers = sorted(all_atomic_numbers)
                for atomic_num in sorted_atomic_numbers:
                    elem_symbol = ELEMENT_SYMBOLS.get(atomic_num, f"Z{atomic_num}")
                    header.extend([elem_symbol, f"{elem_symbol} +/-"])
                
                writer.writerow(header)
                
                # Write data rows
                for row in chemistry_rows:
                    data_row = [
                        row["Date"],
                        row["Test #"],
                        row["Serial #"],
                        row.get("Grade1", ""),
                        row.get("Grade2", ""),
                        row.get("Grade3", ""),
                        row["Mode"],
                        ""  # AVG Flag
                    ]
                    
                    # Create dict of element values keyed by atomic number
                    elem_values = {}
                    if "chemistry" in row:
                        for elem_data in row["chemistry"]:
                            atomic_num = elem_data.get("atomicNumber", 0)
                            percent = elem_data.get("percent", "")
                            uncertainty = elem_data.get("uncertainty", "")
                            flags = elem_data.get("flags", 0)
                            
                            # Format value with flags (ND for below detection, etc.)
                            value_str = ""
                            error_str = ""
                            
                            # Check if below LOD (Less than Limit of Detection)
                            if flags & 8:  # TYPE_LESS_LOD
                                value_str = "ND"
                                error_str = f"< {percent:.2f}" if isinstance(percent, (int, float)) else ""
                            elif isinstance(percent, (int, float)) and isinstance(uncertainty, (int, float)):
                                value_str = f"{percent:.2f}"
                                error_str = f"{uncertainty:.2f}"
                            
                            elem_values[atomic_num] = (value_str, error_str)
                    
                    # Add element values in order
                    for atomic_num in sorted_atomic_numbers:
                        if atomic_num in elem_values:
                            data_row.extend([elem_values[atomic_num][0], elem_values[atomic_num][1]])
                        else:
                            data_row.extend(["", ""])
                    
                    writer.writerow(data_row)
            
            print(f"[COMBO TEST 3] Chemistry data saved to {chemistry_csv}")
        except Exception as e:
            print(f"[COMBO TEST 3] Error saving chemistry data: {e}")
            import traceback
            traceback.print_exc()
    
    return f"[OK] Combo Test 3 completed - {test_num:06d}: " + ", ".join(results)


@app.callback(
    Output("x550-quick-combo-test-status", "children"),
    Input("btn-x550-quick-combo-test", "n_clicks"),
    State("store-x550", "data"),
    prevent_initial_call=True,
)
def x550_quick_combo_test(_n_clicks, x550_data):
    """Combined test: 1 Mining test then 1 Soil test - both use same test number"""
    if not x550_data or not x550_data.get("x550_connected"):
        log_button_click("Combo Test")
        return "[ERROR] X550 not connected"
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        log_button_click("Combo Test")
        return "[ERROR] Missing base URL"
    
    # Get test number once for the entire combo
    test_num = get_next_test_number()
    log_button_click("Combo Test", test_number=f"{test_num:06d}")
    
    results = []
    mining_result = None
    soil_result = None
    
    # Execute Mining test first
    try:
        app_mode = "Mining"
        test_url = f"{base_url}/api/v2/test/final"
        
        print(f"[COMBO TEST] Running Mining test - {test_num:06d}")
        test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)
        
        if test_r.ok:
            try:
                mining_result = test_r.json()
                
                # Save Mining spectra
                if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                    now = datetime.datetime.now()
                    timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"
                    
                    if "spectra" in mining_result:
                        for spec in mining_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)
                            
                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}.csv"
                            csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)
                            
                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (cps)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    f.write(f"{energy},{intensity}\n")
                
                results.append(f"Mining: OK")
                print(f"[COMBO TEST] Mining test completed - {test_num:06d}")
            except Exception as e:
                print(f"[COMBO TEST] Mining test error: {e}")
                results.append("Mining: failed")
        else:
            results.append("Mining: failed")
    except Exception as e:
        print(f"[COMBO TEST] Mining test error: {e}")
        results.append("Mining: failed")
    
    # Execute Soil test second (same test number)
    try:
        app_mode = "Soil"
        test_url = f"{base_url}/api/v2/test/final"
        
        print(f"[COMBO TEST] Running Soil test - {test_num:06d}")
        test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)
        
        if test_r.ok:
            try:
                soil_result = test_r.json()
                
                # Save Soil spectra (same test number, same timestamp)
                if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                    now = datetime.datetime.now()
                    timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"
                    
                    if "spectra" in soil_result:
                        for spec in soil_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)
                            
                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}.csv"
                            csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)
                            
                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (cps)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    f.write(f"{energy},{intensity}\n")
                
                results.append(f"Soil: OK")
                print(f"[COMBO TEST] Soil test completed - {test_num:06d}")
            except Exception as e:
                print(f"[COMBO TEST] Soil test error: {e}")
                results.append("Soil: failed")
        else:
            results.append("Soil: failed")
    except Exception as e:
        print(f"[COMBO TEST] Soil test error: {e}")
        results.append("Soil: failed")
    
    # Save single screenshot after both tests complete
    if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"
        screenshot_name = f"{test_num:06d}_{timestamp}_photo.png"
        screenshot_path = os.path.join(SAVED_FOLDER, screenshot_name)
        save_x550_screenshot(base_url, screenshot_path)
    
    return f"[OK] Combo {test_num:06d} complete - {', '.join(results)}"


@app.callback(
    Output("x550-combo-sequence-store", "data"),
    Output("x550-combo-sequence-status", "children"),
    Output("x550-combo-sequence-timer", "disabled"),
    Output("x550-combo-sequence-current-status", "children"),
    Output("x550-combo-sequence-countdown", "children"),
    Input("btn-x550-start-combo-sequence", "n_clicks"),
    State("x550-combo-count", "value"),
    State("store-x550", "data"),
    prevent_initial_call=True,
)
def start_x550_combo_sequence(_n_clicks, combo_count, x550_data):
    """Start combo sequence: Run tests back-to-back without timers"""
    if not x550_data or not x550_data.get("x550_connected"):
        return None, "[ERROR] X550 not connected", True, "", ""
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        return None, "[ERROR] Missing base URL", True, "", ""
    
    if not combo_count or combo_count < 1:
        return None, "[ERROR] Invalid count", True, "", ""
    
    first_num = None
    last_num = None
    results = []

    for i in range(combo_count):
        test_num = get_next_test_number()
        if first_num is None:
            first_num = test_num
        last_num = test_num

        log_button_click("Combo Test", test_number=f"{test_num:06d}")

        # Mining
        try:
            app_mode = "Mining"
            test_url = f"{base_url}/api/v2/test/final"
            print(f"[COMBO SEQUENCE] Running Mining test - {test_num:06d}")
            test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)

            if test_r.ok:
                mining_result = test_r.json()

                if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                    now = datetime.datetime.now()
                    timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"

                    if "spectra" in mining_result:
                        for spec in mining_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)

                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}.csv"
                            csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)

                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (cps)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    f.write(f"{energy},{intensity}\n")

                results.append("Mining: OK")
            else:
                results.append("Mining: failed")
        except Exception as e:
            print(f"[COMBO SEQUENCE] Mining test error: {e}")
            results.append("Mining: failed")

        # Soil
        try:
            app_mode = "Soil"
            test_url = f"{base_url}/api/v2/test/final"
            print(f"[COMBO SEQUENCE] Running Soil test - {test_num:06d}")
            test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)

            if test_r.ok:
                soil_result = test_r.json()

                if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                    now = datetime.datetime.now()
                    timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"

                    if "spectra" in soil_result:
                        for spec in soil_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)

                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}.csv"
                            csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)

                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (cps)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    f.write(f"{energy},{intensity}\n")

                    screenshot_name = f"{test_num:06d}_{timestamp}_photo.png"
                    screenshot_path = os.path.join(SAVED_FOLDER, screenshot_name)
                    save_x550_screenshot(base_url, screenshot_path)

                results.append("Soil: OK")
            else:
                results.append("Soil: failed")
        except Exception as e:
            print(f"[COMBO SEQUENCE] Soil test error: {e}")
            results.append("Soil: failed")

        log_button_click("Combo Test Complete", is_button=False, test_number=f"{test_num:06d}")

        if i == 0 and combo_count > 1:
            time.sleep(5)

    if first_num is not None and last_num is not None:
        log_button_click(
            f"Combo Sequence Complete: {first_num:06d} to {last_num:06d}",
            is_button=False,
            total_tests=combo_count,
        )

    return None, f"[OK] Combo sequence complete ({combo_count} tests)", True, "", ""




@app.callback(
    Output("x550-combo-sequence-store", "data", allow_duplicate=True),
    Output("x550-combo-sequence-status", "children", allow_duplicate=True),
    Output("x550-combo-sequence-timer", "disabled", allow_duplicate=True),
    Output("x550-combo-sequence-current-status", "children", allow_duplicate=True),
    Output("x550-combo-sequence-countdown", "children", allow_duplicate=True),
    Input("btn-x550-abort-combo-sequence", "n_clicks"),
    State("x550-combo-sequence-store", "data"),
    State("store-x550", "data"),
    prevent_initial_call=True,
)
def abort_x550_combo_sequence(_n_clicks, seq, x550_data):
    """Abort the combo sequence"""
    if not x550_data or not x550_data.get("x550_connected"):
        return None, "[ERROR] X550 not connected", True, "", ""
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        return None, "[ERROR] Missing base URL", True, "", ""
    
    try:
        # Try to abort the test on the analyzer
        abort_urls = [
            f"{base_url}/api/v2/test/abort",
            f"{base_url}/api/v2/abort",
        ]
        
        for abort_url in abort_urls:
            try:
                r = requests.post(abort_url, timeout=5)
                if r.ok:
                    print(f"[ABORT-COMBO] Successfully sent abort to {abort_url}")
                    break
            except requests.RequestException:
                pass
    except Exception as e:
        print(f"[ABORT-COMBO] Error sending abort: {e}")
    
    # Clear sequence state
    seq = None
    return seq, "[OK] Combo sequence aborted", True, "", ""


@app.callback(
    Output("x550-combo-sequence-store", "data", allow_duplicate=True),
    Output("x550-combo-sequence-status", "children", allow_duplicate=True),
    Output("x550-combo-sequence-current-status", "children", allow_duplicate=True),
    Input("btn-x550-start-combo-sequence-2", "n_clicks"),
    State("x550-combo-count", "value"),
    State("store-x550", "data"),
    prevent_initial_call=True,
)
def start_x550_combo_sequence_2(_n_clicks, combo_count, x550_data):
    """Start combo sequence 2: Run 2 tests with Forward button in between"""
    import os
    import datetime
    import requests
    global TRAY_SEQUENCE_ROW
    
    if not x550_data or not x550_data.get("x550_connected"):
        return None, "[ERROR] X550 not connected", ""
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        return None, "[ERROR] Missing base URL", ""
    
    if not combo_count or combo_count < 1:
        return None, "[ERROR] Invalid count", ""

    first_num = None
    last_num = None
    results = []
    current_status = ""

    for i in range(combo_count):
        test_num = get_next_test_number()
        if first_num is None:
            first_num = test_num
        last_num = test_num

        log_button_click("Combo Test", test_number=f"{test_num:06d}")
        
        # Generate timestamp once per test (used for both mining and soil)
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"

        # Mining
        try:
            app_mode = "Mining"
            test_url = f"{base_url}/api/v2/test/final"
            print(f"[COMBO SEQUENCE 2] Running Mining test - {test_num:06d}")
            test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)

            if test_r.ok:
                mining_result = test_r.json()
                num_spectra = len(mining_result.get("spectra", []))
                print(f"[COMBO SEQUENCE 2] Mining test received {num_spectra} spectra")

                if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                    if "spectra" in mining_result:
                        for spec in mining_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)

                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}.csv"
                            csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)

                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (cps)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    f.write(f"{energy},{intensity}\n")

                results.append(f"Mining: OK ({num_spectra} beams)")
            else:
                print(f"[COMBO SEQUENCE 2] Mining test failed with status {test_r.status_code}: {test_r.text[:200]}")
                results.append(f"Mining: failed ({test_r.status_code})")
        except requests.Timeout:
            print(f"[COMBO SEQUENCE 2] Mining test timeout")
            results.append("Mining: timeout")
        except Exception as e:
            print(f"[COMBO SEQUENCE 2] Mining test error: {e}")
            results.append(f"Mining: error ({str(e)[:50]})")

        # Soil
        try:
            app_mode = "Soil"
            test_url = f"{base_url}/api/v2/test/final"
            print(f"[COMBO SEQUENCE 2] Running Soil test - {test_num:06d}")
            test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)

            if test_r.ok:
                soil_result = test_r.json()
                num_spectra = len(soil_result.get("spectra", []))
                print(f"[COMBO SEQUENCE 2] Soil test received {num_spectra} spectra")

                if SAVED_FOLDER and os.path.exists(SAVED_FOLDER):
                    if "spectra" in soil_result:
                        for spec in soil_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)

                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}.csv"
                            csv_filepath = os.path.join(SAVED_FOLDER, csv_filename)

                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (cps)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    f.write(f"{energy},{intensity}\n")

                    screenshot_name = f"{test_num:06d}_{timestamp}_photo.png"
                    screenshot_path = os.path.join(SAVED_FOLDER, screenshot_name)
                    save_x550_screenshot(base_url, screenshot_path)

                results.append(f"Soil: OK ({num_spectra} beams)")
            else:
                print(f"[COMBO SEQUENCE 2] Soil test failed with status {test_r.status_code}: {test_r.text[:200]}")
                results.append(f"Soil: failed ({test_r.status_code})")
        except requests.Timeout:
            print(f"[COMBO SEQUENCE 2] Soil test timeout")
            results.append("Soil: timeout")
        except Exception as e:
            print(f"[COMBO SEQUENCE 2] Soil test error: {e}")
            results.append(f"Soil: error ({str(e)[:50]})")

        log_button_click("Combo Test Complete", is_button=False, test_number=f"{test_num:06d}")

        # After first test, execute Forward button before second test
        if i < combo_count - 1:
            try:
                print(f"[COMBO SEQUENCE 2] Executing Forward button")
                if not _TRAY_INSTANCE or not _TRAY_INSTANCE.is_connected():
                    current_status = "[WARN] Tray not connected - Forward skipped"
                    print("[COMBO SEQUENCE 2] Tray not connected - Forward skipped")
                else:
                    # Read tray_sequence.txt
                    seq_file = os.path.join(os.path.dirname(__file__), 'tray_sequence.txt')
                    if os.path.exists(seq_file):
                        with open(seq_file, 'r') as f:
                            lines = f.readlines()
                        
                        # Check if we're at the end of the file
                        if TRAY_SEQUENCE_ROW < len(lines):
                            # Parse the current row
                            row_data = lines[TRAY_SEQUENCE_ROW].strip().split('\t')
                            if len(row_data) >= 2:
                                try:
                                    x_delta = float(row_data[0])
                                    y_delta = float(row_data[1])
                                    # Move tray by the delta amounts (relative movement)
                                    _TRAY_INSTANCE._send("G91")
                                    if x_delta != 0 or y_delta != 0:
                                        _TRAY_INSTANCE._send(f"G0 X{x_delta} Y{y_delta} F3000")
                                    _TRAY_INSTANCE._send("G90")
                                    TRAY_SEQUENCE_ROW += 1
                                    current_status = f"Forward: X{x_delta:+.2f} Y{y_delta:+.2f} (Row {TRAY_SEQUENCE_ROW})"
                                    print(f"[COMBO SEQUENCE 2] Forward executed: X{x_delta:+.2f} Y{y_delta:+.2f}")
                                except ValueError as ve:
                                    current_status = f"[WARN] Forward parse error: {ve}"
                                    print(f"[COMBO SEQUENCE 2] Could not parse coordinates: {ve}")
                            else:
                                current_status = f"[WARN] Invalid row format at row {TRAY_SEQUENCE_ROW}"
                        else:
                            current_status = f"[WARN] Reached end of sequence (row {TRAY_SEQUENCE_ROW})"
                            print(f"[COMBO SEQUENCE 2] Reached end of sequence")
                    else:
                        current_status = "[WARN] tray_sequence.txt not found"
                        print(f"[COMBO SEQUENCE 2] tray_sequence.txt not found")
            except Exception as e:
                current_status = f"[WARN] Forward error: {e}"
                print(f"[COMBO SEQUENCE 2] Error executing Forward: {e}")

    if first_num is not None and last_num is not None:
        log_button_click(
            f"Combo Sequence Complete: {first_num:06d} to {last_num:06d}",
            is_button=False,
            total_tests=combo_count,
        )

    return None, f"[OK] Combo sequence 2 complete ({combo_count} tests)", current_status


@app.callback(
    Output("sample-other-text", "style"),
    Output("store-sample-type", "data"),
    Input("sample-type-dropdown", "value"),
    State("sample-other-text", "value"),
    prevent_initial_call=False,
)
def update_sample_type(selected_sample, custom_text):
    """Update sample type and show/hide custom text input"""
    # Show text input only if "other" is selected
    text_style = {"marginTop": "10px"} if selected_sample == "other" else {"display": "none", "marginTop": "10px"}
    
    # Store the actual sample value
    store_value = custom_text if selected_sample == "other" and custom_text else selected_sample
    
    return text_style, store_value


@app.callback(
    Output("x550-combo-sequence-store", "data", allow_duplicate=True),
    Output("x550-combo-sequence-status", "children", allow_duplicate=True),
    Output("x550-combo-sequence-current-status", "children", allow_duplicate=True),
    Input("btn-x550-start-combo-sequence-3", "n_clicks"),
    State("x550-combo-count", "value"),
    State("store-x550", "data"),
    State("store-sample-type", "data"),
    prevent_initial_call=True,
)
def start_x550_combo_sequence_3(_n_clicks, combo_count, x550_data, sample_type, override_test_numbers=None, override_save_dir=None):
    """Start combo sequence 3: Run Combo Test 3 (CPS) with Forward button in between, reset sequence row"""
    import os
    import datetime
    import requests
    import csv
    global TRAY_SEQUENCE_ROW, FIRST_CUP_X, FIRST_CUP_Y
    
    # Check if sample type is specified
    if not sample_type or sample_type == "not specified":
        return None, "[ERROR] Please specify a sample type before starting", ""
    
    # Reset tray sequence to start
    TRAY_SEQUENCE_ROW = 2
    print(f"[COMBO SEQUENCE 3] Reset tray sequence to row {TRAY_SEQUENCE_ROW}")
    
    if not x550_data or not x550_data.get("x550_connected"):
        return None, "[ERROR] X550 not connected", ""
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        return None, "[ERROR] Missing base URL", ""
    
    if not combo_count or combo_count < 1:
        return None, "[ERROR] Invalid count", ""
    
    # Move to first cup position before starting combo sequence
    if _TRAY_INSTANCE and _TRAY_INSTANCE.is_connected():
        try:
            _TRAY_INSTANCE.goto(x=FIRST_CUP_X, y=FIRST_CUP_Y, z=0)
            print(f"[COMBO SEQUENCE 3] Moved to first cup (X={FIRST_CUP_X}, Y={FIRST_CUP_Y})")
            # Wait for tray to settle before starting tests
            time.sleep(5)
            print("[COMBO SEQUENCE 3] Tray settled, starting tests (5s pause)")
        except Exception as e:
            print(f"[COMBO SEQUENCE 3] Warning: Could not move to first cup: {e}")

    # Resolve sequence test numbers and save folder (supports overrides for Start BX)
    now = datetime.datetime.now()
    date_str = now.strftime("%Y_%m_%d")

    if override_test_numbers is not None:
        x550_test_numbers = [int(n) for n in override_test_numbers]
        if len(x550_test_numbers) < 1:
            return None, "[ERROR] No override test numbers provided", ""
        if len(x550_test_numbers) != combo_count:
            return None, f"[ERROR] Override test number count ({len(x550_test_numbers)}) does not match combo count ({combo_count})", ""
        first_test_num = x550_test_numbers[0]
    else:
        first_test_num = get_next_test_number()
        x550_test_numbers = [first_test_num]
        for _ in range(combo_count - 1):
            x550_test_numbers.append(get_next_test_number())

    if override_save_dir:
        test_subfolder = override_save_dir
        try:
            os.makedirs(test_subfolder, exist_ok=True)
        except Exception as e:
            print(f"[COMBO SEQUENCE 3] Could not use override subfolder: {test_subfolder}: {e}")
            test_subfolder = SAVED_FOLDER
    else:
        subfolder_name = f"{first_test_num:06d}_{date_str}_{sample_type}_{combo_count}"
        test_subfolder = os.path.join(SAVED_FOLDER, subfolder_name)
        try:
            os.makedirs(test_subfolder, exist_ok=True)
        except Exception as e:
            print(f"[COMBO SEQUENCE 3] Could not create subfolder: {test_subfolder}: {e}")
            test_subfolder = SAVED_FOLDER

    first_num = None
    last_num = None
    results = []
    current_status = ""

    # Now run tests using the resolved list of test numbers
    for i in range(combo_count):
        test_num = x550_test_numbers[i]
        if first_num is None:
            first_num = test_num
        last_num = test_num

        # Assign timestamp for this test
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"

        log_button_click("Combo Test 3", test_number=f"{test_num:06d}")
        chemistry_rows = []

        # Mining
        try:
            app_mode = "Mining"
            test_url = f"{base_url}/api/v2/test/final"
            print(f"[COMBO SEQUENCE 3] Running Mining test - {test_num:06d}")
            test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)

            if test_r.ok:
                mining_result = test_r.json()
                num_spectra = len(mining_result.get("spectra", []))
                print(f"[COMBO SEQUENCE 3] Mining test received {num_spectra} spectra")

                if test_subfolder and os.path.exists(test_subfolder):
                    # Use the subfolder for all outputs
                    if "spectra" in mining_result:
                        shot_num = 1
                        for spec in mining_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)
                            livetime = spec.get("liveTime", "N/A")
                            livetimemultiplier = spec.get("liveTimeMultiplier", "N/A")
                            # Calculate CPS conversion
                            total_count = sum(spectrum_data) if spectrum_data else 0
                            cps_conversion = 1.0
                            if isinstance(livetime, (int, float)) and isinstance(livetimemultiplier, (int, float)) and livetime > 0:
                                cps_conversion = (livetimemultiplier / livetime)
                                corrected_counts = total_count * livetimemultiplier / livetime
                                print(f"[COMBO SEQUENCE 3] Mining Shot {shot_num}: Total counts={total_count}, Corrected CPS={corrected_counts:.2f}")
                            shot_num += 1
                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}_{sample_type}.csv"
                            csv_filepath = os.path.join(test_subfolder, csv_filename)
                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (CPS)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    intensity_cps = intensity * cps_conversion
                                    f.write(f"{energy},{intensity_cps}\n")
                    # Extract chemistry data for Mining
                    if "testData" in mining_result and "chemistry" in mining_result["testData"]:
                        chem = mining_result["testData"]["chemistry"]
                        test_data = mining_result["testData"]
                        date_str = now.strftime("%Y-%m-%d %H:%M:%S")
                        serial = mining_result.get("serialNumber", "X550-Unknown")
                        chemistry_rows.append({
                            "Date": date_str,
                            "Test #": test_num,
                            "Serial #": serial,
                            "Mode": "Mining",
                            "Grade1": test_data.get("firstGradeMatch", ""),
                            "Grade2": test_data.get("secondGradeMatch", ""),
                            "Grade3": test_data.get("thirdGradeMatch", ""),
                            "chemistry": chem
                        })

                results.append(f"Mining: OK ({num_spectra} beams)")
            else:
                print(f"[COMBO SEQUENCE 3] Mining test failed with status {test_r.status_code}")
                results.append(f"Mining: failed ({test_r.status_code})")
        except requests.Timeout:
            print(f"[COMBO SEQUENCE 3] Mining test timeout")
            results.append("Mining: timeout")
        except Exception as e:
            print(f"[COMBO SEQUENCE 3] Mining test error: {e}")
            results.append(f"Mining: error ({str(e)[:50]})")

        # Soil
        try:
            app_mode = "Soil"
            test_url = f"{base_url}/api/v2/test/final"
            print(f"[COMBO SEQUENCE 3] Running Soil test - {test_num:06d}")
            test_r = requests.post(test_url, params={"mode": app_mode}, json={}, timeout=60)

            if test_r.ok:
                soil_result = test_r.json()
                num_spectra = len(soil_result.get("spectra", []))
                print(f"[COMBO SEQUENCE 3] Soil test received {num_spectra} spectra")

                if test_subfolder and os.path.exists(test_subfolder):
                    if "spectra" in soil_result:
                        shot_num = 1
                        for spec in soil_result["spectra"]:
                            beam_name = spec.get("beamName", "Unknown")
                            spectrum_data = spec.get("data", [])
                            energy_offset = spec.get("energyOffset", 0)
                            energy_slope = spec.get("energySlope", 1)
                            livetime = spec.get("liveTime", "N/A")
                            livetimemultiplier = spec.get("liveTimeMultiplier", "N/A")
                            # Calculate CPS conversion
                            total_count = sum(spectrum_data) if spectrum_data else 0
                            cps_conversion = 1.0
                            if isinstance(livetime, (int, float)) and isinstance(livetimemultiplier, (int, float)) and livetime > 0:
                                cps_conversion = (livetimemultiplier / livetime)
                                corrected_counts = total_count * livetimemultiplier / livetime
                                print(f"[COMBO SEQUENCE 3] Soil Shot {shot_num}: Total counts={total_count}, Corrected CPS={corrected_counts:.2f}")
                            shot_num += 1
                            csv_filename = f"{test_num:06d}_{timestamp}_{beam_name}_{sample_type}.csv"
                            csv_filepath = os.path.join(test_subfolder, csv_filename)
                            with open(csv_filepath, 'w') as f:
                                f.write("Energy (keV),Intensity (CPS)\n")
                                for bin_idx, intensity in enumerate(spectrum_data):
                                    energy = energy_offset + (bin_idx * energy_slope)
                                    intensity_cps = intensity * cps_conversion
                                    f.write(f"{energy},{intensity_cps}\n")
                    # Extract chemistry data for Soil
                    if "testData" in soil_result and "chemistry" in soil_result["testData"]:
                        chem = soil_result["testData"]["chemistry"]
                        test_data = soil_result["testData"]
                        date_str = now.strftime("%Y-%m-%d %H:%M:%S")
                        serial = soil_result.get("serialNumber", "X550-Unknown")
                        chemistry_rows.append({
                            "Date": date_str,
                            "Test #": test_num,
                            "Serial #": serial,
                            "Mode": "Soil",
                            "Grade1": test_data.get("firstGradeMatch", ""),
                            "Grade2": test_data.get("secondGradeMatch", ""),
                            "Grade3": test_data.get("thirdGradeMatch", ""),
                            "chemistry": chem
                        })

                results.append(f"Soil: OK ({num_spectra} beams)")
            else:
                print(f"[COMBO SEQUENCE 3] Soil test failed with status {test_r.status_code}")
                results.append(f"Soil: failed ({test_r.status_code})")
        except requests.Timeout:
            print(f"[COMBO SEQUENCE 3] Soil test timeout")
            results.append("Soil: timeout")
        except Exception as e:
            print(f"[COMBO SEQUENCE 3] Soil test error: {e}")
            results.append(f"Soil: error ({str(e)[:50]})")

        # Save chemistry data to CSV for this test
        if chemistry_rows and test_subfolder and os.path.exists(test_subfolder):
            try:
                chem_now = datetime.datetime.now()
                chem_timestamp = chem_now.strftime("%Y_%m_%d_%H%M%S") + f"{int(chem_now.microsecond / 10000):02d}"
                chemistry_csv = os.path.join(test_subfolder, f"{test_num:06d}_{chem_timestamp}_chemistry_{sample_type}.csv")
                ELEMENT_SYMBOLS = {
                    1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O", 9: "F", 10: "Ne",
                    11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P", 16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca",
                    21: "Sc", 22: "Ti", 23: "V", 24: "Cr", 25: "Mn", 26: "Fe", 27: "Co", 28: "Ni", 29: "Cu", 30: "Zn",
                    31: "Ga", 32: "Ge", 33: "As", 34: "Se", 35: "Br", 36: "Kr", 37: "Rb", 38: "Sr", 39: "Y", 40: "Zr",
                    41: "Nb", 42: "Mo", 43: "Tc", 44: "Ru", 45: "Rh", 46: "Pd", 47: "Ag", 48: "Cd", 49: "In", 50: "Sn",
                    51: "Sb", 52: "Te", 53: "I", 54: "Xe", 55: "Cs", 56: "Ba", 57: "La", 58: "Ce", 59: "Pr", 60: "Nd",
                    61: "Pm", 62: "Sm", 63: "Eu", 64: "Gd", 65: "Tb", 66: "Dy", 67: "Ho", 68: "Er", 69: "Tm", 70: "Yb",
                    71: "Lu", 72: "Hf", 73: "Ta", 74: "W", 75: "Re", 76: "Os", 77: "Ir", 78: "Pt", 79: "Au", 80: "Hg",
                    81: "Tl", 82: "Pb", 83: "Bi", 84: "Po", 85: "At", 86: "Rn", 87: "Fr", 88: "Ra", 89: "Ac", 90: "Th",
                    91: "Pa", 92: "U", 93: "Np", 94: "Pu", 95: "Am", 96: "Cm", 97: "Bk", 98: "Cf", 99: "Es", 100: "Fm"
                }
                
                with open(chemistry_csv, 'w', newline='') as f:
                    writer = csv.writer(f)
                    header = ["Date", "Test #", "Serial #", "Grade Match #1", "Grade Match #2", "Grade Match #3", "Mode", "AVG Flag"]
                    all_atomic_numbers = set()
                    for row in chemistry_rows:
                        if "chemistry" in row:
                            for elem_data in row["chemistry"]:
                                all_atomic_numbers.add(elem_data.get("atomicNumber", 0))
                    sorted_atomic_numbers = sorted(all_atomic_numbers)
                    for atomic_num in sorted_atomic_numbers:
                        elem_symbol = ELEMENT_SYMBOLS.get(atomic_num, f"Z{atomic_num}")
                        header.extend([elem_symbol, f"{elem_symbol} +/-"])
                    writer.writerow(header)
                    for row in chemistry_rows:
                        data_row = [row["Date"], row["Test #"], row["Serial #"], row.get("Grade1", ""), row.get("Grade2", ""), row.get("Grade3", ""), row["Mode"], ""]
                        elem_values = {}
                        if "chemistry" in row:
                            for elem_data in row["chemistry"]:
                                atomic_num = elem_data.get("atomicNumber", 0)
                                percent = elem_data.get("percent", "")
                                uncertainty = elem_data.get("uncertainty", "")
                                flags = elem_data.get("flags", 0)
                                value_str = ""
                                error_str = ""
                                if flags & 8:
                                    value_str = "ND"
                                    error_str = f"< {percent:.2f}" if isinstance(percent, (int, float)) else ""
                                elif isinstance(percent, (int, float)) and isinstance(uncertainty, (int, float)):
                                    value_str = f"{percent:.2f}"
                                    error_str = f"{uncertainty:.2f}"
                                elem_values[atomic_num] = (value_str, error_str)
                        for atomic_num in sorted_atomic_numbers:
                            if atomic_num in elem_values:
                                data_row.extend([elem_values[atomic_num][0], elem_values[atomic_num][1]])
                            else:
                                data_row.extend(["", ""])
                        writer.writerow(data_row)
                print(f"[COMBO SEQUENCE 3] Chemistry data saved to {chemistry_csv}")
            except Exception as e:
                print(f"[COMBO SEQUENCE 3] Error saving chemistry data: {e}")

        # Save single screenshot after both tests complete
        if test_subfolder and os.path.exists(test_subfolder):
            now = datetime.datetime.now()
            timestamp = now.strftime("%Y_%m_%d_%H%M%S") + f"{int(now.microsecond / 10000):02d}"
            screenshot_name = f"{test_num:06d}_{timestamp}_photo_{sample_type}.png"
            screenshot_path = os.path.join(test_subfolder, screenshot_name)
            save_x550_screenshot(base_url, screenshot_path)

        log_button_click("Combo Test 3 Complete", is_button=False, test_number=f"{test_num:06d}")

        # After each test (except last), execute Forward button
        if i < combo_count - 1:
            try:
                print(f"[COMBO SEQUENCE 3] Executing Forward button")
                if not _TRAY_INSTANCE or not _TRAY_INSTANCE.is_connected():
                    current_status = "[WARN] Tray not connected - Forward skipped"
                    print("[COMBO SEQUENCE 3] Tray not connected - Forward skipped")
                else:
                    seq_file = os.path.join(os.path.dirname(__file__), 'tray_sequence.txt')
                    if os.path.exists(seq_file):
                        with open(seq_file, 'r') as f:
                            lines = f.readlines()
                        if TRAY_SEQUENCE_ROW < len(lines):
                            row_data = lines[TRAY_SEQUENCE_ROW].strip().split('\t')
                            if len(row_data) >= 2:
                                try:
                                    x_delta = float(row_data[0])
                                    y_delta = float(row_data[1])
                                    _TRAY_INSTANCE._send("G91")
                                    if x_delta != 0 or y_delta != 0:
                                        _TRAY_INSTANCE._send(f"G0 X{x_delta} Y{y_delta} F3000")
                                    _TRAY_INSTANCE._send("G90")
                                    TRAY_SEQUENCE_ROW += 1
                                    current_status = f"Forward: X{x_delta:+.2f} Y{y_delta:+.2f} (Row {TRAY_SEQUENCE_ROW})"
                                    print(f"[COMBO SEQUENCE 3] Forward executed: X{x_delta:+.2f} Y{y_delta:+.2f}")
                                except ValueError as ve:
                                    current_status = f"[WARN] Forward parse error: {ve}"
                                    print(f"[COMBO SEQUENCE 3] Could not parse coordinates: {ve}")
                            else:
                                current_status = f"[WARN] Invalid row format at row {TRAY_SEQUENCE_ROW}"
                        else:
                            current_status = f"[WARN] Reached end of sequence (row {TRAY_SEQUENCE_ROW})"
                            print(f"[COMBO SEQUENCE 3] Reached end of sequence")
                    else:
                        current_status = "[WARN] tray_sequence.txt not found"
                        print(f"[COMBO SEQUENCE 3] tray_sequence.txt not found")
            except Exception as e:
                current_status = f"[WARN] Forward error: {e}"
                print(f"[COMBO SEQUENCE 3] Error executing Forward: {e}")

    if first_num is not None and last_num is not None:
        log_button_click(f"Combo Sequence 3 Complete: {first_num:06d} to {last_num:06d}", is_button=False, total_tests=combo_count)

    global _LAST_SEQUENCE3_SUBFOLDER, _LAST_SEQUENCE3_TEST_NUMS
    _LAST_SEQUENCE3_SUBFOLDER = test_subfolder
    _LAST_SEQUENCE3_TEST_NUMS = list(x550_test_numbers)

    return None, f"[OK] Combo sequence 3 complete ({combo_count} tests)", current_status


@app.callback(
    Output("x550-combo-sequence-store", "data", allow_duplicate=True),
    Output("x550-combo-sequence-status", "children", allow_duplicate=True),
    Output("basler-photo-frame", "children", allow_duplicate=True),
    Input("btn-x550-start-combo-sequence-3-basler", "n_clicks"),
    State("x550-combo-count", "value"),
    State("store-x550", "data"),
    State("store-sample-type", "data"),
    State("store-basler", "data"),
    State("store-video-zoom", "data"),
    prevent_initial_call=True,
)
def start_x550_and_basler_combined(_n_clicks, combo_count, x550_data, sample_type, basler_data, zoom):
    """Start X550 combo sequence 3 (identical to Start X), then Basler sequence with shared test numbers and folder."""
    log_button_click("Start XB (X550 + Basler)")

    print("\n" + "="*60)
    print("PHASE 1: X550 COMBO SEQUENCE 3 (same logic as Start X)")
    print("="*60)

    _, x550_msg, _ = start_x550_combo_sequence_3(None, combo_count, x550_data, sample_type)
    if x550_msg.startswith("[ERROR]"):
        return None, x550_msg, dash.no_update

    test_subfolder = _LAST_SEQUENCE3_SUBFOLDER
    x550_test_numbers = _LAST_SEQUENCE3_TEST_NUMS
    print(f"[START XB] X550 complete. Subfolder: {test_subfolder}, Test numbers: {x550_test_numbers}")

    print("\n" + "="*60)
    print("PHASE 2: BASLER SEQUENCE")
    print("="*60)

    # Start XB-only serial sync: Start X sends G91/G0/G90 without reading responses,
    # leaving stale 'ok' bytes in the serial buffer. Basler's _read_response would
    # consume those stale oks instead of waiting for real motion, so the tray never
    # actually moves between Basler shots. Two-phase drain fixes this:
    try:
        if _TRAY_INSTANCE and _TRAY_INSTANCE.is_connected():
            # Phase 1: wait for all X550 serial bytes to arrive, then wipe the buffer
            time.sleep(1)
            try:
                if _TRAY_INSTANCE.ser:
                    _TRAY_INSTANCE.ser.reset_input_buffer()
            except Exception:
                pass
            # Phase 2: M400 now arrives at firmware AFTER X550 bytes; firmware responds
            # only when the motion planner is truly empty (all motion complete)
            try:
                _TRAY_INSTANCE._send("M400")
                _TRAY_INSTANCE._read_response(timeout=15)
            except Exception:
                pass
            # Phase 3: clear anything that snuck in during M400 execution, restore abs mode
            try:
                if _TRAY_INSTANCE.ser:
                    _TRAY_INSTANCE.ser.reset_input_buffer()
            except Exception:
                pass
            try:
                _TRAY_INSTANCE._send("G90")
                _TRAY_INSTANCE._read_response(timeout=2.0)
            except Exception:
                pass
            print("[START XB] Tray serial sync complete — buffer clean, absolute mode restored")
    except Exception as sync_err:
        print(f"[START XB] Warning: pre-Basler tray sync issue: {sync_err}")

    try:
        basler_msg, basler_preview = start_basler_sequence(
            _n_clicks=None,
            basler_data=basler_data,
            sample_type=sample_type,
            zoom=zoom,
            override_test_numbers=x550_test_numbers,
            override_save_dir=test_subfolder
        )
        print(f"[START XB] Basler result: {basler_msg}")
        log_button_click("Start XB Complete", is_button=False, total_tests=combo_count)
        return None, f"{x550_msg}\n{basler_msg}", basler_preview

    except Exception as e:
        print(f"[START XB] Basler error: {e}")
        import traceback
        traceback.print_exc()
        return None, f"[ERROR] Basler sequence failed: {e}", dash.no_update


@app.callback(
    Output("x550-combo-sequence-store", "data", allow_duplicate=True),
    Output("x550-combo-sequence-status", "children", allow_duplicate=True),
    Output("basler-photo-frame", "children", allow_duplicate=True),
    Input("btn-x550-start-combo-sequence-3-basler-first", "n_clicks"),
    State("x550-combo-count", "value"),
    State("store-x550", "data"),
    State("store-sample-type", "data"),
    State("store-basler", "data"),
    State("store-video-zoom", "data"),
    prevent_initial_call=True,
)
def start_basler_and_x550_combined(_n_clicks, combo_count, x550_data, sample_type, basler_data, zoom):
    """Start BX: Basler sequence first, then X550 combo sequence 3 with shared test numbers and folder."""
    import os
    import datetime

    log_button_click("Start BX (Basler + X550)")

    if not combo_count or combo_count < 1:
        return None, "[ERROR] Invalid count", dash.no_update

    sample_value = str(sample_type).strip() if sample_type is not None else ""
    if (not sample_value) or (sample_value.lower() in {"not specified", "other"}):
        return None, "[ERROR] Sample type is missing. Please select a sample type before Start BX", dash.no_update

    # Create folder first using the same naming pattern as Start X
    now = datetime.datetime.now()
    date_str = now.strftime("%Y_%m_%d")
    first_test_num = get_next_test_number()
    shared_test_numbers = [first_test_num]
    for _ in range(combo_count - 1):
        shared_test_numbers.append(get_next_test_number())

    save_root = SAVED_FOLDER if SAVED_FOLDER else os.path.dirname(__file__)
    subfolder_name = f"{first_test_num:06d}_{date_str}_{sample_value}_{combo_count}"
    test_subfolder = os.path.join(save_root, subfolder_name)
    try:
        os.makedirs(test_subfolder, exist_ok=True)
    except Exception as e:
        return None, f"[ERROR] Could not create save folder: {e}", dash.no_update

    print("\n" + "="*60)
    print("PHASE 1: BASLER SEQUENCE")
    print("="*60)
    print(f"[START BX] Shared subfolder: {test_subfolder}, Test numbers: {shared_test_numbers}")
    print(f"[START BX] Basler start coordinates (same as Check first cup Basler): X={BASLER_FIRST_CUP_X}, Y={BASLER_FIRST_CUP_Y}, Z={TRAY_WORK_Z}")

    try:
        if _TRAY_INSTANCE and _TRAY_INSTANCE.is_connected():
            if _TRAY_INSTANCE.ser:
                try:
                    _TRAY_INSTANCE.ser.reset_input_buffer()
                except Exception:
                    pass
            time.sleep(0.05)
            _TRAY_INSTANCE._send("G90")
            _TRAY_INSTANCE._read_response(timeout=0.6)
            print("[START BX] Pre-Basler tray sync complete (buffer cleared, absolute mode forced)")
    except Exception as sync_err:
        print(f"[START BX] Warning: pre-Basler tray sync issue: {sync_err}")

    try:
        basler_msg, basler_preview = start_basler_sequence(
            _n_clicks=None,
            basler_data=basler_data,
            sample_type=sample_value,
            zoom=zoom,
            override_test_numbers=shared_test_numbers,
            override_save_dir=test_subfolder
        )
        if str(basler_msg).startswith("[ERROR]"):
            return None, basler_msg, basler_preview
        print(f"[START BX] Basler result: {basler_msg}")
    except Exception as e:
        print(f"[START BX] Basler error: {e}")
        import traceback
        traceback.print_exc()
        return None, f"[ERROR] Basler sequence failed: {e}", dash.no_update

    print("\n" + "="*60)
    print("PHASE 2: X550 COMBO SEQUENCE 3")
    print("="*60)

    try:
        _, x550_msg, _ = start_x550_combo_sequence_3(
            None,
            combo_count,
            x550_data,
            sample_value,
            override_test_numbers=shared_test_numbers,
            override_save_dir=test_subfolder
        )
        if str(x550_msg).startswith("[ERROR]"):
            return None, x550_msg, basler_preview

        log_button_click("Start BX Complete", is_button=False, total_tests=combo_count)
        return None, f"{basler_msg}\n{x550_msg}", basler_preview
    except Exception as e:
        print(f"[START BX] X550 error: {e}")
        import traceback
        traceback.print_exc()
        return None, f"[ERROR] X550 sequence failed: {e}", basler_preview


@app.callback(
    Output("x550-live-status", "children"),
    Input("x550-status-poll", "n_intervals"),
)
def update_x550_live_status(_n_intervals):
    """Update live X550 status by reading the latest log entry."""
    def read_last_log_line(path):
        try:
            if not os.path.exists(path):
                return ""
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                if size == 0:
                    return ""
                read_size = min(4096, size)
                f.seek(-read_size, os.SEEK_END)
                chunk = f.read().decode(errors="ignore")
            lines = [line.strip() for line in chunk.splitlines() if line.strip()]
            return lines[-1] if lines else ""
        except Exception:
            return ""

    log_dir = SAVED_FOLDER if SAVED_FOLDER else os.path.dirname(__file__)
    log_file = os.path.join(log_dir, "dashboard_clicks.log")
    backup_log_file = os.path.join(log_dir, "dashboard_clicks_backup.log")

    last_line = read_last_log_line(log_file) or read_last_log_line(backup_log_file)

    if not last_line:
        return "On standby"

    match = re.search(r"test_number=(\d+)", last_line)
    test_num = match.group(1) if match else None

    if "Combo Test Complete" in last_line:
        return f"Test {test_num} done" if test_num else "Test done"
    if "Combo Test" in last_line:
        return f"Shooting test {test_num}" if test_num else "Shooting test"
    if "Combo Sequence Complete" in last_line or "Combo sequence aborted" in last_line:
        return "On standby"

    return "On standby"


@app.callback(
    Output("x550-calibrate-status-inline", "children"),
    Output("x550-calibrate-store", "data"),
    Output("x550-calibrate-timer", "disabled"),
    Input("btn-x550-calibrate-inline", "n_clicks"),
    State("store-x550", "data"),
    prevent_initial_call=True,
)
def x550_calibrate(_n_clicks, x550_data):
    """Trigger energy calibration on the X-550 (XRF analyzer)"""
    log_button_click("Calibrate")
    if not x550_data or not x550_data.get("x550_connected"):
        return "[ERROR] X550 not connected", None, True
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        return "[ERROR] Missing base URL", None, True
    
    # First, move tray to position calibration location
    try:
        if _TRAY_INSTANCE and _TRAY_INSTANCE.is_connected():
            _TRAY_INSTANCE._send("G28 X Y")
            _TRAY_INSTANCE._read_response()
            _TRAY_INSTANCE.goto(x=130.0, y=55.2, z=0.1)
            print("[CALIBRATE] Tray moved to calibration position")
            # Wait for tray to settle before starting calibration
            time.sleep(5)
            print("[CALIBRATE] Tray settled, proceeding with calibration (5s pause)")
        else:
            print("[CALIBRATE] Warning: Tray not connected, skipping position move")
    except Exception as e:
        print(f"[CALIBRATE] Warning: Could not move tray to position: {e}")
    
    try:
        # Energy calibration endpoint for X-series XRF analyzers
        cal_url = f"{base_url}/api/v2/energyCal"
        
        print(f"[CALIBRATE] Starting energy calibration at {cal_url}")
        r = requests.post(cal_url, timeout=60)
        
        if r.ok:
            print(f"[CALIBRATE] Success - HTTP {r.status_code}")
            try:
                response_data = r.json()
                print(f"[CALIBRATE] Response: {response_data}")
                status = response_data.get("status", "UNKNOWN")
                error_code = response_data.get("errorCode", 0)
                
                if error_code != 0:
                    return f"[ERROR] Calibration error code: {error_code}", None, True
                    
            except Exception as e:
                print(f"[CALIBRATE] Could not parse response: {e}")
            
            # Start polling for calibration completion
            return "[OK] Calibration started - checking status...", {"polling": True, "start_time": time.time()}, False
        else:
            error_text = r.text[:500] if r.text else "No error message"
            print(f"[CALIBRATE] Failed - HTTP {r.status_code}: {error_text}")
            return f"[ERROR] Calibration failed - HTTP {r.status_code}: {error_text}", None, True
        
    except requests.exceptions.Timeout:
        print("[CALIBRATE] Request timeout")
        return "[ERROR] Calibration request timed out", None, True
    except Exception as e:
        print(f"[CALIBRATE] Error: {e}")
        import traceback
        traceback.print_exc()
        return f"[ERROR] Calibration failed: {type(e).__name__}", None, True


@app.callback(
    Output("x550-calibrate-status-inline", "children", allow_duplicate=True),
    Output("x550-calibrate-store", "data", allow_duplicate=True),
    Output("x550-calibrate-timer", "disabled", allow_duplicate=True),
    Input("x550-calibrate-timer", "n_intervals"),
    State("x550-calibrate-store", "data"),
    State("store-x550", "data"),
    prevent_initial_call=True,
)
def check_calibration_status(_n, cal_data, x550_data):
    """Poll the X-550 status to check if calibration is complete"""
    if not cal_data or not cal_data.get("polling"):
        return dash.no_update, cal_data, True
    
    if not x550_data or not x550_data.get("x550_connected"):
        return "[ERROR] X550 disconnected", None, True
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        return "[ERROR] Missing base URL", None, True
    
    try:
        elapsed = time.time() - cal_data.get("start_time", 0)
        
        # Check calibration coefficients to see if they changed
        cal_url = f"{base_url}/api/v2/energyCal"
        r = requests.get(cal_url, timeout=5)
        
        if r.ok:
            cal_coeffs = r.json()
            slope = cal_coeffs.get("slope", 0)
            offset = cal_coeffs.get("offset", 0)
            
            # Store initial coefficients on first check
            if "initial_slope" not in cal_data:
                cal_data["initial_slope"] = slope
                cal_data["initial_offset"] = offset
                return f"[WAIT] Calibrating... ({int(elapsed)}s, initial: slope={slope:.3f}, offset={offset:.3f})", cal_data, False
            
            # Check if coefficients changed (indicating calibration completed)
            initial_slope = cal_data.get("initial_slope", 0)
            initial_offset = cal_data.get("initial_offset", 0)
            
            if abs(slope - initial_slope) > 0.001 or abs(offset - initial_offset) > 0.001:
                # Coefficients changed - calibration complete!
                print(f"[CALIBRATE] Calibration completed after {elapsed:.1f}s")
                print(f"[CALIBRATE] Old: slope={initial_slope:.3f}, offset={initial_offset:.3f}")
                print(f"[CALIBRATE] New: slope={slope:.3f}, offset={offset:.3f}")
                return f"[OK] Calibration complete! ({elapsed:.1f}s) - slope={slope:.3f}, offset={offset:.3f}", None, True
        
        # Also check status for additional info
        status_url = f"{base_url}/api/v2/status"
        r_status = requests.get(status_url, timeout=5)
        
        if r_status.ok:
            status = r_status.json()
            is_ecal_needed = status.get("isECalNeeded", True)
            
            if elapsed > 120:
                # Timeout after 2 minutes
                print(f"[CALIBRATE] Calibration timeout after {elapsed:.1f}s")
                return "[WARNING] Calibration timeout - coefficients unchanged. Manually calibrate on device?", None, True
            else:
                # Still waiting
                return f"[WAIT] Calibrating... ({int(elapsed)}s, isECalNeeded={is_ecal_needed})", cal_data, False
        else:
            return f"[ERROR] Status check failed - HTTP {r_status.status_code}", None, True
            
    except Exception as e:
        print(f"[CALIBRATE] Status check error: {e}")
        return f"[ERROR] Status check failed: {type(e).__name__}", None, True



@app.callback(
    Output("x550-heartbeat", "children"),
    Input("x550-heartbeat-timer", "n_intervals"),
)
def x550_heartbeat_monitor(_n):
    """Monitor X550 connection health"""
    if not _X550_INSTANCE or not _X550_INSTANCE.is_connected():
        return "Heartbeat: Not connected"
    
    try:
        ok = _X550_INSTANCE.heartbeat()
        if ok:
            return "Heartbeat: X550 OK"
        else:
            return "Heartbeat: X550 not responding"
    except Exception:
        return "Heartbeat: Error"


# Screenshot callback removed - feature disabled


@app.callback(
    Output("store-folder", "data"),
    Output("folder-feedback", "children"),
    Output("input-folder", "value"),
    Input("btn-save-folder", "n_clicks"),
    Input("store-folder", "data"),
    Input("input-folder", "value"),
    prevent_initial_call=False,
)
def save_folder(n_clicks, stored_path, input_value):
    import os
    import json
    
    ctx = dash.callback_context.triggered_id
    
    CONFIG_FILE = os.path.join(os.path.dirname(__file__), '.robotray_config.json')

    # Initial load
    if ctx is None:
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                folder = config.get('folder_path')
                if folder:
                    return folder, f"[OK] Loaded folder: {folder}", folder
        except Exception as e:
            return stored_path or "", f"[ERROR] Could not load config: {e}", stored_path or ""

        if stored_path:
            return stored_path, f"[OK] Loaded folder: {stored_path}", stored_path

        return "", "", ""

    # Save button
    if ctx == "btn-save-folder":
        log_button_click("Save Folder", folder_path=input_value if input_value else "none")
        folder = (input_value or "").strip()
        if not folder:
            return stored_path or "", "[ERROR] Please enter a folder path", input_value

        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                return stored_path or "", f"[ERROR] Cannot create folder: {e}", input_value

        config = {}
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
        except Exception:
            config = {}

        config['folder_path'] = folder

        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f)
            return folder, f"[OK] Saved folder: {folder}", folder
        except Exception as e:
            return stored_path or "", f"[ERROR] Could not save config: {e}", input_value

    return stored_path or "", "", input_value


@app.callback(
    Output("btn-x-plus", "disabled"),
    Output("btn-x-minus", "disabled"),
    Output("btn-y-plus", "disabled"),
    Output("btn-y-minus", "disabled"),
    Output("btn-z-plus", "disabled"),
    Output("btn-z-minus", "disabled"),
    Input("store-edit-mode", "data"),
)
def gate_directional_buttons(edit_mode):
    disabled = not edit_mode
    return disabled, disabled, disabled, disabled, disabled, disabled

@app.callback(
    Output("tray-log", "children"),
    Output("store-edit-mode", "data"),
    Output("tray-position-poll", "disabled"),
    Output("tray-sequence-row", "children"),
    Input("btn-first", "n_clicks"),
    Input("btn-last", "n_clicks"),
    Input("btn-edit-first", "n_clicks"),
    Input("btn-save-first", "n_clicks"),
    Input("btn-first-basler", "n_clicks"),
    Input("btn-last-basler", "n_clicks"),
    Input("btn-edit-first-basler", "n_clicks"),
    Input("btn-save-first-basler", "n_clicks"),
    Input("btn-x-plus", "n_clicks"),
    Input("btn-x-minus", "n_clicks"),
    Input("btn-y-plus", "n_clicks"),
    Input("btn-y-minus", "n_clicks"),
    Input("btn-z-plus", "n_clicks"),
    Input("btn-z-minus", "n_clicks"),
    Input("btn-home", "n_clicks"),
    Input("btn-forward-sequence", "n_clicks"),
    Input("btn-reset-sequence", "n_clicks"),
    Input("btn-position-tray", "n_clicks"),
    Input("store-keyboard", "data"),
    Input("input-step-size", "value"),
    State("store-edit-mode", "data"),
    prevent_initial_call=True,
)
def tray_checks(n_first, n_last, n_edit, n_save, n_first_basler, n_last_basler, n_edit_basler, n_save_basler, n_xp, n_xm, n_yp, n_ym, n_zp, n_zm, n_home, n_forward, n_reset, n_position, keyboard_data, step_size, edit_mode):
    import dash
    global FIRST_CUP_X, FIRST_CUP_Y, LAST_CUP_X, LAST_CUP_Y
    global BASLER_FIRST_CUP_X, BASLER_FIRST_CUP_Y, BASLER_LAST_CUP_X, BASLER_LAST_CUP_Y
    global TRAY_SEQUENCE_ROW, TRAY_WORK_Z
    ctx = dash.callback_context.triggered_id

    if not _TRAY_INSTANCE or not _TRAY_INSTANCE.is_connected():
        return "Tray not connected", False, True, f"Row: {TRAY_SEQUENCE_ROW}"

    step = float(step_size) if step_size else 10.0

    if ctx == "store-keyboard":
        if not edit_mode:
            return "[WARN] Keyboard control is active only in Edit mode", False, True, f"Row: {TRAY_SEQUENCE_ROW}"

        key = (keyboard_data or {}).get("key")
        key_map = {
            "ArrowLeft": "btn-x-minus",
            "ArrowRight": "btn-x-plus",
            "ArrowUp": "btn-y-plus",
            "ArrowDown": "btn-y-minus",
            "o": "btn-z-minus",
            "O": "btn-z-minus",
            "p": "btn-z-plus",
            "P": "btn-z-plus",
        }
        mapped_ctx = key_map.get(key)
        if not mapped_ctx:
            return dash.no_update, dash.no_update, dash.no_update, f"Row: {TRAY_SEQUENCE_ROW}"
        ctx = mapped_ctx

    if ctx == "btn-first":
        _TRAY_INSTANCE.goto(x=FIRST_CUP_X, y=FIRST_CUP_Y, z=TRAY_WORK_Z)
        return f"[OK] Moved to X550 first cup (X={FIRST_CUP_X}, Y={FIRST_CUP_Y}, Z={TRAY_WORK_Z})", False, True, f"Row: {TRAY_SEQUENCE_ROW}"

    if ctx == "btn-last":
        _TRAY_INSTANCE.goto(x=LAST_CUP_X, y=LAST_CUP_Y, z=TRAY_WORK_Z)
        return f"[OK] Moved to X550 last cup (X={LAST_CUP_X}, Y={LAST_CUP_Y}, Z={TRAY_WORK_Z})", False, True, f"Row: {TRAY_SEQUENCE_ROW}"
    
    if ctx == "btn-edit-first":
        _TRAY_INSTANCE.goto(x=FIRST_CUP_X, y=FIRST_CUP_Y, z=TRAY_WORK_Z)
        return "[OK] X550 edit mode active\n[OK] Use arrow keys for X/Y, O/P for Z, or click directional buttons\n[OK] Click 'Save first cup X550' when done", True, False, f"Row: {TRAY_SEQUENCE_ROW}"
    
    if ctx == "btn-save-first":
        try:
            pos = _TRAY_INSTANCE.get_position(strict=True)
            _check_tray_limits(x=pos[0], y=pos[1], z=pos[2])
            # Update global variables
            FIRST_CUP_X = pos[0]
            FIRST_CUP_Y = pos[1]
            TRAY_WORK_Z = pos[2]
            # Calculate last cup position: X = first_x + 63, Y = first_y - 98
            LAST_CUP_X = FIRST_CUP_X + 63
            LAST_CUP_Y = FIRST_CUP_Y - 98
            # Save to config file
            config = load_config_dict()
            config['x550_first_cup_x'] = FIRST_CUP_X
            config['x550_first_cup_y'] = FIRST_CUP_Y
            config['tray_work_z'] = TRAY_WORK_Z
            save_config_dict(config)
            verify_cfg = load_config_dict()
            if 'x550_first_cup_x' not in verify_cfg or 'x550_first_cup_y' not in verify_cfg:
                raise IOError(f"Config verify failed after save: {CONFIG_FILE}")
            print(f"[CONFIG] Saved X550 first cup position: X={FIRST_CUP_X}, Y={FIRST_CUP_Y}")
            print(f"[CONFIG] Calculated X550 last cup position: X={LAST_CUP_X}, Y={LAST_CUP_Y}")
            print(f"[CONFIG] Saved tray work Z: Z={TRAY_WORK_Z}")
            print(f"[CONFIG] Saved file: {CONFIG_FILE}")
            return f"[OK] X550 first cup: X={FIRST_CUP_X}, Y={FIRST_CUP_Y}, Z={TRAY_WORK_Z}\n[OK] X550 last cup: X={LAST_CUP_X}, Y={LAST_CUP_Y}, Z={TRAY_WORK_Z}", False, False, f"Row: {TRAY_SEQUENCE_ROW}"
        except Exception as e:
            print(f"[ERROR] Could not save X550 first cup position: {e}")
            return f"[ERROR] Could not read tray position: {e}", False, False, f"Row: {TRAY_SEQUENCE_ROW}"

    if ctx == "btn-first-basler":
        _goto_basler_first_cup()
        return f"[OK] Moved to Basler first cup (X={BASLER_FIRST_CUP_X}, Y={BASLER_FIRST_CUP_Y}, Z={TRAY_WORK_Z})", False, True, f"Row: {TRAY_SEQUENCE_ROW}"

    if ctx == "btn-last-basler":
        _TRAY_INSTANCE.goto(x=BASLER_LAST_CUP_X, y=BASLER_LAST_CUP_Y, z=TRAY_WORK_Z)
        return f"[OK] Moved to Basler last cup (X={BASLER_LAST_CUP_X}, Y={BASLER_LAST_CUP_Y}, Z={TRAY_WORK_Z})", False, True, f"Row: {TRAY_SEQUENCE_ROW}"

    if ctx == "btn-edit-first-basler":
        _goto_basler_first_cup()
        return "[OK] Basler edit mode active\n[OK] Use arrow keys for X/Y, O/P for Z, or click directional buttons\n[OK] Click 'Save first cup Basler' when done", True, False, f"Row: {TRAY_SEQUENCE_ROW}"

    if ctx == "btn-save-first-basler":
        try:
            pos = _TRAY_INSTANCE.get_position(strict=True)
            _check_tray_limits(x=pos[0], y=pos[1], z=pos[2])
            BASLER_FIRST_CUP_X = pos[0]
            BASLER_FIRST_CUP_Y = pos[1]
            TRAY_WORK_Z = pos[2]
            BASLER_LAST_CUP_X = BASLER_FIRST_CUP_X + 63
            BASLER_LAST_CUP_Y = BASLER_FIRST_CUP_Y - 98

            config = load_config_dict()
            config['basler_first_cup_x'] = BASLER_FIRST_CUP_X
            config['basler_first_cup_y'] = BASLER_FIRST_CUP_Y
            config['tray_work_z'] = TRAY_WORK_Z
            save_config_dict(config)
            verify_cfg = load_config_dict()
            if 'basler_first_cup_x' not in verify_cfg or 'basler_first_cup_y' not in verify_cfg:
                raise IOError(f"Config verify failed after save: {CONFIG_FILE}")

            print(f"[CONFIG] Saved Basler first cup position: X={BASLER_FIRST_CUP_X}, Y={BASLER_FIRST_CUP_Y}")
            print(f"[CONFIG] Calculated Basler last cup position: X={BASLER_LAST_CUP_X}, Y={BASLER_LAST_CUP_Y}")
            print(f"[CONFIG] Saved tray work Z: Z={TRAY_WORK_Z}")
            print(f"[CONFIG] Saved file: {CONFIG_FILE}")
            return f"[OK] Basler first cup: X={BASLER_FIRST_CUP_X}, Y={BASLER_FIRST_CUP_Y}, Z={TRAY_WORK_Z}\n[OK] Basler last cup: X={BASLER_LAST_CUP_X}, Y={BASLER_LAST_CUP_Y}, Z={TRAY_WORK_Z}", False, False, f"Row: {TRAY_SEQUENCE_ROW}"
        except Exception as e:
            print(f"[ERROR] Could not save Basler first cup position: {e}")
            return f"[ERROR] Could not read tray position: {e}", False, False, f"Row: {TRAY_SEQUENCE_ROW}"
    
    # Directional movement
    if ctx == "btn-x-plus":
        _move_tray_relative_and_wait(x_delta=step)
        return f"→ Moved X+{step}mm", True, False, f"Row: {TRAY_SEQUENCE_ROW}"
    
    if ctx == "btn-x-minus":
        _move_tray_relative_and_wait(x_delta=-step)
        return f"← Moved X-{step}mm", True, False, f"Row: {TRAY_SEQUENCE_ROW}"
    
    if ctx == "btn-y-plus":
        _move_tray_relative_and_wait(y_delta=step)
        return f"↑ Moved Y+{step}mm", True, False, f"Row: {TRAY_SEQUENCE_ROW}"
    
    if ctx == "btn-y-minus":
        _move_tray_relative_and_wait(y_delta=-step)
        return f"↓ Moved Y-{step}mm", True, False, f"Row: {TRAY_SEQUENCE_ROW}"
    
    if ctx == "btn-z-plus":
        _move_tray_relative_and_wait(z_delta=step)
        return f"↑ Moved Z+{step}mm", True, False, f"Row: {TRAY_SEQUENCE_ROW}"
    
    if ctx == "btn-z-minus":
        _move_tray_relative_and_wait(z_delta=-step)
        return f"↓ Moved Z-{step}mm", True, False, f"Row: {TRAY_SEQUENCE_ROW}"
    
    if ctx == "btn-home":
        try:
            _TRAY_INSTANCE._send("G28 X Y Z")
            _TRAY_INSTANCE._read_response()
            return "[OK] Homed X, Y, and Z together", False, True, f"Row: {TRAY_SEQUENCE_ROW}"
        except Exception as e:
            print(f"[TRAY] Home command failed: {e}")
            return f"[ERROR] Home failed: {e}", False, False, f"Row: {TRAY_SEQUENCE_ROW}"

    if ctx == "btn-forward-sequence":
        try:
            move_msg = _move_tray_sequence_forward_once()
            return f"[OK] {move_msg}", False, False, f"Row: {TRAY_SEQUENCE_ROW}"
        except Exception as e:
            print(f"[ERROR] Forward sequence error: {e}")
            return f"[ERROR] {str(e)}", False, False, f"Row: {TRAY_SEQUENCE_ROW}"
    
    if ctx == "btn-reset-sequence":
        TRAY_SEQUENCE_ROW = 2
        print(f"[TRAY] Sequence reset to row {TRAY_SEQUENCE_ROW}")
        return "[OK] Sequence reset to start (row 2)", False, False, f"Row: {TRAY_SEQUENCE_ROW}"
    
    if ctx == "btn-position-tray":
        _TRAY_INSTANCE._send("G28 X Y")
        _TRAY_INSTANCE._read_response()
        _TRAY_INSTANCE.goto(x=173.0, y=58.0, z=TRAY_WORK_Z)
        return f"[OK] Homed X and Y, then moved to position (X=173.0, Y=58.0, Z={TRAY_WORK_Z})", False, True, f"Row: {TRAY_SEQUENCE_ROW}"

    return dash.no_update, dash.no_update, dash.no_update, f"Row: {TRAY_SEQUENCE_ROW}"


@app.callback(
    Output("tray-first-cup-coords", "children"),
    Output("tray-last-cup-coords", "children"),
    Output("tray-current-coords", "children"),
    Output("tray-home-coords", "children"),
    Input("tray-position-poll", "n_intervals"),
    Input("store-connection", "data"),
    State("store-edit-mode", "data"),
)
def update_tray_coordinates(_n_intervals, connection_data, edit_mode):
    """Update coordinate displays"""
    global FIRST_CUP_X, FIRST_CUP_Y, LAST_CUP_X, LAST_CUP_Y, TRAY_WORK_Z, LAST_TRAY_POS, TRAY_SEQUENCE_RUNNING
    
    if not connection_data or not connection_data.get("tray_connected"):
        return "", "", "", ""
    
    first_cup = f"X={FIRST_CUP_X:.1f}, Y={FIRST_CUP_Y:.1f}, Z={TRAY_WORK_Z:.1f}"
    last_cup = f"X={LAST_CUP_X:.1f}, Y={LAST_CUP_Y:.1f}, Z={TRAY_WORK_Z:.1f}"
    home = "X=0, Y=0, Z=0.0"
    
    # Show current position; avoid M114 polling while an automated sequence is running.
    if _TRAY_INSTANCE and _TRAY_INSTANCE.is_connected():
        try:
            if not TRAY_SEQUENCE_RUNNING:
                pos = _TRAY_INSTANCE.get_position(strict=False)
                LAST_TRAY_POS = pos
                current = f"X={pos[0]:.1f}, Y={pos[1]:.1f}, Z={pos[2]:.1f}"
            elif LAST_TRAY_POS is not None:
                current = f"X={LAST_TRAY_POS[0]:.1f}, Y={LAST_TRAY_POS[1]:.1f}, Z={LAST_TRAY_POS[2]:.1f}"
            else:
                current = ""
        except Exception:
            current = ""
    else:
        current = ""
    
    return first_cup, last_cup, current, home


@app.callback(
    Output("basler-tray-first-cup-coords", "children"),
    Output("basler-tray-last-cup-coords", "children"),
    Output("basler-tray-current-coords", "children"),
    Input("tray-position-poll", "n_intervals"),
    Input("store-connection", "data"),
)
def update_basler_tray_coordinates(_n_intervals, connection_data):
    """Update Basler tray coordinate displays"""
    global BASLER_FIRST_CUP_X, BASLER_FIRST_CUP_Y, BASLER_LAST_CUP_X, BASLER_LAST_CUP_Y, TRAY_WORK_Z, LAST_TRAY_POS

    if not connection_data or not connection_data.get("tray_connected"):
        return "", "", ""

    first_cup = f"X={BASLER_FIRST_CUP_X:.1f}, Y={BASLER_FIRST_CUP_Y:.1f}, Z={TRAY_WORK_Z:.1f}"
    last_cup = f"X={BASLER_LAST_CUP_X:.1f}, Y={BASLER_LAST_CUP_Y:.1f}, Z={TRAY_WORK_Z:.1f}"

    # Reuse cached value from update_tray_coordinates to avoid a second M114 query.
    if LAST_TRAY_POS is not None:
        current = f"X={LAST_TRAY_POS[0]:.1f}, Y={LAST_TRAY_POS[1]:.1f}, Z={LAST_TRAY_POS[2]:.1f}"
    else:
        current = ""

    return first_cup, last_cup, current


@app.callback(
    Output("photo-status", "children"),
    Output("photo-preview", "src"),
    Output("photo-preview", "style"),
    Input("btn-take-photo", "n_clicks"),
    State("store-folder", "data"),
    State("store-x550", "data"),
    prevent_initial_call=True,
)
def take_photo(_n_clicks, folder_path, x550_data):
    """Capture screenshot from X-550 analyzer and save to output folder"""
    log_button_click("Take Photo")
    import os
    import datetime
    import base64
    
    # Check if X-550 is connected
    if not x550_data or not x550_data.get("x550_connected"):
        return "[ERROR] X-550 not connected", "", {"display": "none"}
    
    base_url = x550_data.get("x550_url")
    if not base_url:
        return "[ERROR] Missing X-550 URL", "", {"display": "none"}
    
    # Check if folder path is configured
    if not folder_path:
        return "[ERROR] Please configure output folder first", "", {"display": "none"}
    
    # Create output subfolder for photos
    output_folder = os.path.join(folder_path, "photos")
    try:
        os.makedirs(output_folder, exist_ok=True)
    except Exception as e:
        return f"[ERROR] Could not create photos folder: {e}", "", {"display": "none"}
    
    # Try different screenshot endpoints
    screenshot_endpoints = [
        f"{base_url}/api/v2/screenshot",
        f"{base_url}/api/v1/screenshot",
        f"{base_url}/api/screenshot",
    ]
    
    for endpoint in screenshot_endpoints:
        try:
            print(f"[SCREENSHOT] Trying endpoint: {endpoint}")
            r = requests.get(endpoint, timeout=10)
            
            if r.status_code == 200:
                # Generate filename with timestamp
                now = datetime.datetime.now()
                timestamp = now.strftime("%Y%m%d_%H%M%S")
                test_num = get_next_test_number()
                filename = f"{test_num:06d}_{timestamp}_screenshot.png"
                filepath = os.path.join(output_folder, filename)
                
                # Save screenshot
                with open(filepath, 'wb') as f:
                    f.write(r.content)
                
                # Convert to base64 for preview
                img_base64 = base64.b64encode(r.content).decode('utf-8')
                img_src = f"data:image/png;base64,{img_base64}"
                
                preview_style = {
                    "maxWidth": "100%",
                    "maxHeight": "400px",
                    "marginTop": "10px",
                    "border": "1px solid #ccc",
                    "borderRadius": "4px",
                    "display": "block",
                }
                
                print(f"[SCREENSHOT] Successfully saved to {filepath}")
                return f"[OK] Screenshot saved: {filename}", img_src, preview_style
                
        except requests.RequestException as e:
            print(f"[SCREENSHOT] Failed at {endpoint}: {e}")
            continue
    
    return "[ERROR] Could not capture screenshot from X-550. No valid screenshot endpoint found.", "", {"display": "none"}


def save_x550_screenshot(base_url, filepath):
    """Save X-550 screenshot to a specific filepath."""
    screenshot_endpoints = [
        f"{base_url}/api/v2/screenshot",
        f"{base_url}/api/v1/screenshot",
        f"{base_url}/api/screenshot",
    ]
    for endpoint in screenshot_endpoints:
        try:
            r = requests.get(endpoint, timeout=10)
            if r.status_code == 200:
                with open(filepath, "wb") as f:
                    f.write(r.content)
                print(f"[SCREENSHOT] Saved to {filepath}")
                return True
        except Exception as e:
            print(f"[SCREENSHOT] Failed at {endpoint}: {e}")
    return False



if __name__ == "__main__":
    # Load test counter at startup
    load_test_counter()
    # Load cup coordinates at startup
    load_cup_coordinates()
    import threading
    import webbrowser
    import json
    import os

    # Load saved folder path from config
    CONFIG_FILE = os.path.join(os.path.dirname(__file__), '.robotray_config.json')
    SAVED_FOLDER = r"C:\Users\phuynh\Projects\robotray\sample_outputs"
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                SAVED_FOLDER = config.get('folder_path', SAVED_FOLDER)
                print(f"[CONFIG] Loaded saved folder: {SAVED_FOLDER}")
    except Exception as e:
        print(f"[CONFIG] Could not load config: {e}")

    app_start_time = time.strftime('%H:%M:%S')
    
    # CREATE LAYOUT HERE with current time
    app.layout = dbc.Container(
        fluid=True,
        children=[
            dbc.Alert(f"APP STARTED AT {app_start_time}", color="danger", className="mb-3"),
            html.H3("Step 1 - Connect Devices", className="mt-3"),
            dcc.Store(id="store-connection"),
            dcc.Store(id="store-x550"),
            dcc.Store(id="store-basler"),
            dcc.Store(id="store-x550-app"),
            dcc.Store(id="x550-combo-sequence-store", data=None),
            dcc.Store(id="x550-calibrate-store"),
            dcc.Store(id="store-folder"),
            dcc.Store(id="store-keyboard", data={}),
            dcc.Interval(id="keyboard-poll", interval=100, n_intervals=0),
            dcc.Interval(id="x550-heartbeat-timer", interval=3000, n_intervals=0, disabled=True),
            dcc.Interval(id="x550-screenshot-timer", interval=2000, n_intervals=0, disabled=True),
            dcc.Interval(id="x550-combo-sequence-timer", interval=100, n_intervals=0, disabled=True),
            dcc.Interval(id="x550-calibrate-timer", interval=2000, n_intervals=0, disabled=True),
            dcc.Interval(id="x550-status-poll", interval=1000, n_intervals=0),
            dcc.Interval(id="video-capture-timer", interval=300, n_intervals=0, disabled=True),
            dcc.Store(id="store-video-zoom", data=1.0),

            dbc.Row(
                [
                    dbc.Col(
                        dbc.Button(
                            "Connect to Tray",
                            id="btn-connect",
                            color="primary",
                            size="lg",
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.Button(
                            "Connect to X550",
                            id="btn-connect-x550",
                            color="secondary",
                            size="lg",
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.Button(
                            "Connect to Basler",
                            id="btn-connect-basler",
                            color="info",
                            size="lg",
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.Input(
                            id="x550-ip",
                            placeholder="X550 IP (default 127.0.0.1, will try 192.168.42.129)",
                            type="text",
                            value="",
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        dbc.Input(
                            id="x550-port",
                            placeholder="Port (optional, e.g. 8080)",
                            type="number",
                        ),
                        width=2,
                    ),
                ],
                className="mb-3",
            ),

            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("TRAY (Ender / Stage)"),
                                    html.Div(id="tray-status"),
                                    html.Div(id="tray-port", className="text-muted mt-1"),
                                ]
                            ),
                            className="h-100",
                        ),
                        width=4,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("X-550 (Pistol)"),
                                    html.Div(id="x550-status"),
                                    html.Div(id="x550-url", className="text-muted mt-1"),
                                    html.Div(id="x550-heartbeat", className="text-muted small mt-1"),
                                ]
                            ),
                            className="h-100",
                        ),
                        width=4,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("Basler (Camera)"),
                                    html.Div(id="basler-status"),
                                    html.Div(id="basler-info", className="text-muted mt-1"),
                                ]
                            ),
                            className="h-100",
                        ),
                        width=4,
                    ),
                ]
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Live Video"),
                        dbc.Row(
                            [
                                dbc.Col(dbc.Button("Video", id="btn-video", color="warning", size="sm", className="w-100"), width=3),
                                dbc.Col(dbc.Button("Zoom In", id="btn-zoom-in", color="secondary", size="sm", className="w-100"), width=3),
                                dbc.Col(dbc.Button("Zoom Out", id="btn-zoom-out", color="secondary", size="sm", className="w-100"), width=3),
                                dbc.Col(dbc.Button("Photo", id="btn-video-photo", color="primary", size="sm", className="w-100"), width=3),
                            ],
                            className="mb-2",
                        ),
                        dbc.Row(
                            [
                                dbc.Col(
                                    dbc.Button("Start basler", id="btn-start-basler", color="success", size="sm", className="w-100"),
                                    width=12,
                                ),
                            ],
                            className="mb-2",
                        ),
                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        html.Div("Live", className="text-muted small mb-1"),
                                        html.Div(id="basler-video-frame"),
                                    ],
                                    md=6,
                                ),
                                dbc.Col(
                                    [
                                        html.Div("Photo", className="text-muted small mb-1"),
                                        html.Div(
                                            id="basler-photo-frame",
                                            children=html.Div(
                                                "No photo yet",
                                                style={"padding": "8px", "border": "2px solid #9e9e9e", "backgroundColor": "#f2f2f2"}
                                            ),
                                        ),
                                    ],
                                    md=6,
                                ),
                            ],
                            align="start",
                        ),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("X-550 Calibration"),
                        dbc.Row(
                            [
                                dbc.Col(
                                    dbc.Button("Position", id="btn-position-tray", color="info", size="lg", style={"display": "none"}),
                                    md="auto",
                                ),
                                dbc.Col(
                                    dbc.Button("Calibrate X550", id="btn-x550-calibrate", color="warning", size="lg"),
                                    md="auto",
                                ),
                            ],
                            className="g-2",
                            align="center",
                        ),
                        html.Div(id="x550-calibrate-status", className="text-muted small mt-2"),
                    ]
                ),
                className="mb-3",
                style={"display": "none"},
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("X-550 Calibration"),
                                    dbc.Button("Calibrate X550", id="btn-x550-calibrate-inline", color="warning", size="lg", style={"width": "100%"}),
                                    html.Div(id="x550-calibrate-status-inline", className="text-muted small mt-2"),
                                ]
                            ),
                            className="mb-3",
                        ),
                        md=2,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("Sample"),
                                    dbc.Row([
                                        dbc.Col([
                                            html.Label("Sample type:", className="small fw-bold"),
                                            dcc.Dropdown(
                                                id="sample-type-dropdown",
                                                options=[
                                                    {"label": "Not specified", "value": "not specified"},
                                                    {"label": "Apatite", "value": "apatite"},
                                                    {"label": "Feldspar", "value": "feldspar"},
                                                    {"label": "Garnet", "value": "garnet"},
                                                    {"label": "Monazite-AUS", "value": "monazite-aus"},
                                                    {"label": "Monazite-BRA", "value": "monazite-bra"},
                                                    {"label": "Nephe", "value": "nephe"},
                                                    {"label": "Quartz", "value": "quartz"},
                                                    {"label": "Rutile", "value": "rutile"},
                                                    {"label": "Tray", "value": "tray"},
                                                    {"label": "Zircon", "value": "zircon"},
                                                    {"label": "Other", "value": "other"},
                                                ],
                                                value="not specified",
                                                clearable=False,
                                            ),
                                        ]),
                                    ]),
                                    dbc.Row([
                                        dbc.Col([
                                            dbc.Input(
                                                id="sample-other-text",
                                                type="text",
                                                placeholder="Specify other sample type",
                                                style={"display": "none", "marginTop": "10px"}
                                            ),
                                        ]),
                                    ], className="mt-2"),
                                    dcc.Store(id="store-sample-type", data="not specified"),
                                ]
                            ),
                            className="mb-3",
                        ),
                        md=5,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("Output folder"),
                                    dbc.InputGroup([
                                        dbc.Input(id="input-folder", type="text", placeholder="Folder path"),
                                        dbc.Button("Save folder", id="btn-save-folder", color="primary"),
                                    ]),
                                    html.Div(id="folder-feedback", className="mt-2"),
                                ]
                            ),
                            className="mb-3",
                        ),
                        md=5,
                    ),
                ]
            ),

            # dbc.Card(
            #     dbc.CardBody(
            #         [
            #             html.H5("X-550 Screen Mirror"),
            #             html.Img(
            #                 id="x550-screenshot",
            #                 alt="X550 analyzer screen",
            #                 style={
            #                     "maxWidth": "100%",
            #                     "maxHeight": "500px",
            #                     "border": "1px solid #ccc",
            #                     "borderRadius": "4px",
            #                     "backgroundColor": "#f0f0f0",
            #                 }
            #             ),
            #             html.Div(id="x550-screenshot-status", className="text-muted small mt-2"),
            #             html.P("(Disabled - screenshot endpoint not working)", className="text-muted small mt-1"),
            #         ]
            #     ),
            #     className="mb-3",
            # ),
            html.Div(id="x550-screenshot", style={"display": "none"}),
            html.Div(id="x550-screenshot-status", style={"display": "none"}),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("X-550 Screenshot"),
                        dbc.Button("Take Photo", id="btn-take-photo", color="success", size="lg", style={"display": "none"}),
                        html.Div(id="photo-status", className="text-muted small mt-2"),
                        html.Img(
                            id="photo-preview",
                            style={
                                "maxWidth": "100%",
                                "maxHeight": "400px",
                                "marginTop": "10px",
                                "border": "1px solid #ccc",
                                "borderRadius": "4px",
                                "display": "none",
                            }
                        ),
                    ]
                ),
                className="mb-3",
                style={"display": "none"},
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Tray Actions"),
                        dbc.Row([
                            dbc.Col([
                                html.H6("X550", className="mb-2"),
                                dbc.Row([
                                    dbc.Col([
                                        dbc.Button("Check first cup X550", id="btn-first", color="info", disabled=True, style={"width": "100%"}),
                                        html.Div(id="tray-first-cup-coords", className="text-muted small mt-1"),
                                    ], width=6),
                                    dbc.Col([
                                        dbc.Button("Check last cup X550", id="btn-last", color="info", disabled=True, style={"width": "100%"}),
                                        html.Div(id="tray-last-cup-coords", className="text-muted small mt-1"),
                                    ], width=6),
                                ], className="mb-3"),
                                dbc.Row([
                                    dbc.Col([
                                        dbc.Button("Edit first cup X550", id="btn-edit-first", color="warning", disabled=True, style={"width": "100%"}),
                                        html.Div(id="tray-current-coords", className="text-primary small fw-bold mt-1"),
                                    ], width=6),
                                    dbc.Col([
                                        dbc.Button("Save first cup X550", id="btn-save-first", color="success", disabled=True, style={"width": "100%"}),
                                    ], width=6),
                                ], className="mb-3"),
                            ], width=6),
                            dbc.Col([
                                html.H6("Basler", className="mb-2"),
                                dbc.Row([
                                    dbc.Col([
                                        dbc.Button("Check first cup Basler", id="btn-first-basler", color="info", disabled=True, style={"width": "100%"}),
                                        html.Div(id="basler-tray-first-cup-coords", className="text-muted small mt-1"),
                                    ], width=6),
                                    dbc.Col([
                                        dbc.Button("Check last cup Basler", id="btn-last-basler", color="info", disabled=True, style={"width": "100%"}),
                                        html.Div(id="basler-tray-last-cup-coords", className="text-muted small mt-1"),
                                    ], width=6),
                                ], className="mb-3"),
                                dbc.Row([
                                    dbc.Col([
                                        dbc.Button("Edit first cup Basler", id="btn-edit-first-basler", color="warning", disabled=True, style={"width": "100%"}),
                                        html.Div(id="basler-tray-current-coords", className="text-primary small fw-bold mt-1"),
                                    ], width=6),
                                    dbc.Col([
                                        dbc.Button("Save first cup Basler", id="btn-save-first-basler", color="success", disabled=True, style={"width": "100%"}),
                                    ], width=6),
                                ], className="mb-3"),
                            ], width=6),
                        ], className="mb-2"),
                        
                        html.Hr(),
                        dbc.Row([
                            dbc.Col([
                                dbc.Button("Home X550 (G28 X Y, then Z0)", id="btn-home", color="primary", disabled=True, style={"width": "100%"}),
                            ], width=4),
                            dbc.Col([
                                dbc.Button("Forward X550", id="btn-forward-sequence", color="secondary", disabled=True, style={"width": "100%"}),
                            ], width=4),
                            dbc.Col([
                                dbc.Button("Reset X550", id="btn-reset-sequence", color="warning", disabled=True, style={"width": "100%"}),
                            ], width=4),
                        ], className="mb-2"),
                        html.Div(id="tray-home-coords", className="text-muted small mt-1"),
                        html.Div(id="tray-sequence-row", className="text-muted small"),
                        
                        html.Hr(),
                        html.H6("Manual Control X550 (active during Edit mode)", className="mt-3"),
                        html.P("Use keyboard: arrow keys (X/Y), O / P (Z), or click buttons below", className="text-muted small"),
                        dcc.Store(id="store-edit-mode", data=False),

                        # Directional controls
                        dbc.Row([
                            dbc.Col([
                                dbc.ButtonGroup([
                                    dbc.Button("Y+", id="btn-y-plus", color="secondary", disabled=True, size="sm"),
                                ], className="d-flex justify-content-center mb-1"),
                                dbc.ButtonGroup([
                                    dbc.Button("X-", id="btn-x-minus", color="secondary", disabled=True, size="sm"),
                                    html.Span("", className="mx-2"),
                                    dbc.Button("X+", id="btn-x-plus", color="secondary", disabled=True, size="sm"),
                                ]),
                                dbc.ButtonGroup([
                                    dbc.Button("Y-", id="btn-y-minus", color="secondary", disabled=True, size="sm"),
                                ], className="d-flex justify-content-center mt-1"),
                            ], width=4),
                            dbc.Col([
                                dbc.ButtonGroup([
                                    dbc.Button("Z+", id="btn-z-plus", color="info", disabled=True, size="sm"),
                                ], className="d-flex justify-content-center mb-1"),
                                html.Div(style={"height": "32px"}),
                                dbc.ButtonGroup([
                                    dbc.Button("Z-", id="btn-z-minus", color="info", disabled=True, size="sm"),
                                ], className="d-flex justify-content-center mt-1"),
                            ], width=2),
                            dbc.Col([
                                html.Label("Step size (mm):"),
                                dbc.Input(id="input-step-size", type="number", value=10, min=0.1, max=50, step=0.1, style={"width": "100px"}),
                            ], width=6),
                        ]),

                        html.Pre(id="tray-log", className="mt-3"),
                        dcc.Interval(id="tray-position-poll", interval=2000, n_intervals=0, disabled=False),
                    ]
                ),
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.Div(),
                    ]
                ),
                style={"display": "none"},
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.Div(),
                    ]
                ),
                style={"display": "none"},
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Combo Sequence"),
                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        html.Label("Count", className="small"),
                                        dbc.Input(
                                            id="x550-combo-count",
                                            type="number",
                                            min=1,
                                            step=1,
                                            value=2,
                                            placeholder="Count",
                                        ),
                                    ],
                                    md=1,
                                ),
                                dbc.Col(
                                    [
                                        html.Label("\u00A0", className="small"),
                                        dbc.Button("Start", id="btn-x550-start-combo-sequence", color="primary", style={"display": "none"}),
                                    ],
                                    md="auto",
                                ),
                                dbc.Col(
                                    [
                                        html.Label("\u00A0", className="small"),
                                        dbc.Button("Start 2", id="btn-x550-start-combo-sequence-2", color="success", style={"display": "none"}),
                                    ],
                                    md="auto",
                                ),
                                dbc.Col(
                                    [
                                        html.Label("\u00A0", className="small"),
                                        dbc.Button("Start X", id="btn-x550-start-combo-sequence-3", color="info"),
                                    ],
                                    md="auto",
                                ),
                                dbc.Col(
                                    [
                                        html.Label("\u00A0", className="small"),
                                        dbc.Button("Start XB", id="btn-x550-start-combo-sequence-3-basler", color="warning"),
                                    ],
                                    md="auto",
                                ),
                                dbc.Col(
                                    [
                                        html.Label("\u00A0", className="small"),
                                        dbc.Button("Start BX", id="btn-x550-start-combo-sequence-3-basler-first", color="secondary"),
                                    ],
                                    md="auto",
                                ),
                                dbc.Col(
                                    [
                                        html.Label("\u00A0", className="small"),
                                        dbc.Button("Abort", id="btn-x550-abort-combo-sequence", color="danger"),
                                    ],
                                    md="auto",
                                ),
                            ],
                            className="g-2",
                            align="center",
                        ),
                        html.Div([
                            html.Div(id="x550-live-status", className="fw-bold", style={"color": "#0b6bcb"}),
                            html.H4(id="x550-combo-sequence-current-status", className="mt-3 mb-2", style={"color": "#0066cc"}),
                            html.H2(id="x550-combo-sequence-countdown", className="mb-2", style={"color": "#ff6600", "fontWeight": "bold"}),
                        ]),
                        html.Div(id="x550-combo-sequence-status", className="text-muted small mt-2"),
                    ]
                ),
                className="mb-3",
            ),

            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Quick Test"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Button("1 Mining Test", id="btn-x550-quick-test", color="success", size="lg"),
                                html.Div(id="x550-quick-test-status", className="text-muted small mt-2"),
                            ], md=4),
                            dbc.Col([
                                dbc.Button("1 Soil Test", id="btn-x550-quick-soil-test", color="info", size="lg"),
                                html.Div(id="x550-quick-soil-test-status", className="text-muted small mt-2"),
                            ], md=4),
                            dbc.Col([
                                dbc.Button("Combo Test", id="btn-x550-quick-combo-test", color="warning", size="lg"),
                                html.Div(id="x550-quick-combo-test-status", className="text-muted small mt-2"),
                            ], md=4),
                        ]),
                        dbc.Row([
                            dbc.Col([
                                dbc.Button("Combo Test 2", id="btn-x550-quick-combo-test-2", color="success", size="lg"),
                                html.Div(id="x550-quick-combo-test-2-status", className="text-muted small mt-2"),
                            ], md=4),
                            dbc.Col([
                                dbc.Button("Combo Test 3", id="btn-x550-quick-combo-test-3", color="info", size="lg"),
                                html.Div(id="x550-quick-combo-test-3-status", className="text-muted small mt-2"),
                            ], md=4),
                        ], className="mt-2"),
                    ]
                ),
                className="mb-3",
            ),

            html.Hr(),
            html.Div(id="system-status"),
        ],
    )

    print("\n" + "="*60)
    print(f"DASH APP STARTING AT {app_start_time}")
    print("="*60 + "\n")

    HOST = "127.0.0.1"
    PORT = 8071

    # Open browser automatically (only on main process, not reloader)
    import os
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        webbrowser.open(f"http://{HOST}:{PORT}/")

    app.run(debug=True, host=HOST, port=PORT)
