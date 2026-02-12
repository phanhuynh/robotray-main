# SciAps X-550 Basic Dashboard (Fixed v2)
# ------------------------------------------------------

from __future__ import annotations
import io, json, zipfile, os, socket, webbrowser, time
import threading
from typing import Any, Dict
from datetime import datetime, timezone

import sys
import requests
import pandas as pd
import serial
import serial.tools.list_ports
import dash
import plotly.graph_objs as go
from dash import Dash, dcc, html, Input, Output, State, no_update

# Ensure local 'sashimi' import path
_PS_PATH = os.path.join(os.getcwd(), "particle-scanner")
if _PS_PATH not in sys.path:
    sys.path.append(_PS_PATH)
try:
    from sashimi.stage import Stage  # for HTTP mode (optional)
except Exception:
    Stage = None  # HTTP mode optional; USB still works

APP_TITLE = "SciAps X-550 Basic"
DEFAULT_PORT_START = 8070

# ---------------------- Helpers ----------------------

def ts_utc():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def find_open_port(start_port: int = DEFAULT_PORT_START) -> int:
    port = start_port
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                in_use = (s.connect_ex(("127.0.0.1", port)) == 0)
            if not in_use:
                return port
            port += 1
        except OSError:
            return port

# ---------------------- App ----------------------

app = Dash(__name__)
app.title = APP_TITLE

app.layout = html.Div([
    html.H3("Ender 3 V2 Stage Controls"),

    # App state used by callbacks
    dcc.Store(id="store-stage-ready"),
    dcc.Store(id="store-key"),
    dcc.Store(id="store-key-ts"),
    dcc.Store(id="store-pocket-1"),
    dcc.Store(id="store-pocket-2"),

    # Timers
    dcc.Interval(id="stage-poll", interval=1500, n_intervals=0, disabled=True),
    dcc.Interval(id="key-poll", interval=200, n_intervals=0),

    # Connection row
    html.Div([
        html.Label("Connection"),
        dcc.Dropdown(id="stage-conn-type", options=[
            {"label": "USB (Serial)", "value": "usb"},
            {"label": "Moonraker HTTP", "value": "http"}
        ], value="usb", clearable=False, style={"width": "180px"}),

        html.Label("Printer Host (http://ip)"),
        dcc.Input(id="printer-host", type="text", value="http://192.168.1.50", style={"width": "24ch"}),
        html.Label("Port"),
        dcc.Input(id="printer-port", type="number", value=7125, style={"width": "10ch"}),

        html.Label("COM Port"),
        dcc.Dropdown(id="printer-com", options=[{"label": "COM4", "value": "COM4"}], value="COM4", style={"width": "220px"}),
        html.Label("Baud"),
        dcc.Input(id="printer-baud", type="number", value=115200, style={"width": "10ch"}),

        html.Button("Connect Stage", id="btn-stage-connect"),
        html.Span(id="stage-connect-status", style={"marginLeft": "8px"}),
        html.Span(id="stage-conn-heartbeat", style={"marginLeft": "8px", "fontStyle": "italic", "color": "#555"}),
    ], style={"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap"}),

    # Actions row
    html.Div([
        html.Button("Home (G28)", id="btn-stage-home"),
        html.Button("Auto Level (G29)", id="btn-stage-level"),
        html.Label("Jog (µm)"),
        dcc.Input(id="jog-um", type="number", value=1000, min=1, step=100, style={"width": "12ch"}),
        html.Label("Pause (s)"),
        dcc.Input(id="seq-pause-sec", type="number", value=2.0, min=0, step=0.5, style={"width": "10ch"}),
        html.Button("Save Location of Cup 1", id="btn-save-pocket-1"),
        html.Button("Save Location of Cup 2", id="btn-save-pocket-2"),
        html.Button("Go to Cup 1", id="btn-goto-pocket-1"),
        html.Button("Go to Cup 2", id="btn-goto-pocket-2"),
        html.Button("Default Location of Top Left Cup 1", id="btn-default-cup-1"),
        html.Button("Default Location of Top Left Cup 2", id="btn-default-cup-2"),
        html.Button("Start Sequence", id="btn-start-sequence"),
    ], style={"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap", "marginTop": "6px"}),

    # Movement controls
    html.Div([
        html.Button("←", id="btn-left"),
        html.Button("→", id="btn-right"),
        html.Button("↑", id="btn-up"),
        html.Button("↓", id="btn-down"),
        html.Button("Z+", id="btn-z-up"),
        html.Button("Z-", id="btn-z-down"),
        html.Span(id="stage-action-status", style={"marginLeft": "16px", "fontStyle": "italic"}),
    ], style={"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap", "marginTop": "8px"}),

    # Cup displays
    html.Div([
        html.Span(id="pocket-1-display"),
        html.Span(" | ", style={"margin": "0 8px"}),
        html.Span(id="pocket-2-display"),
    ], style={"marginTop": "8px"}),
])

# ---------------------- Serial Stage ----------------------

class SerialStage:
    def __init__(self, com_port: str, baud: int = 115200):
        self.ser = serial.Serial(
            com_port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
            write_timeout=1,
        )
        try:
            self.ser.dtr = False
            self.ser.rts = False
            time.sleep(0.05)
            self.ser.dtr = True
            self.ser.rts = True
        except Exception:
            pass
        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception:
            pass
        self._send("M115")
        self.x = 0
        self.y = 0
        self.z = 0

    def _send(self, cmd: str) -> str:
        data = (cmd.strip() + "\r\n").encode("ascii")
        self.ser.write(data)
        self.ser.flush()
        try:
            return self.ser.readline().decode(errors="ignore")
        except Exception:
            return ""

    def move_home(self, home_position=(0,0,0)):
        self._send("G28")
        self.goto(home_position)

    def auto_level(self):
        self._send("G29")

    def move_x(self, distance_um: int):
        self.goto_x(self.x + distance_um)

    def move_y(self, distance_um: int):
        self.goto_y(self.y + distance_um)

    def move_z(self, distance_um: int):
        self.goto_z(self.z + distance_um)

    def goto_x(self, position_um: int):
        self.x = max(0, position_um)
        self._send(f"G0 X {self.x/1000:.3f} F3000")

    def goto_y(self, position_um: int):
        self.y = max(0, position_um)
        self._send(f"G0 Y {self.y/1000:.3f} F3000")

    def goto_z(self, position_um: int):
        self.z = max(0, position_um)
        self._send(f"G0 Z {self.z/1000:.3f} F300")

    def goto(self, pos):
        self.goto_x(pos[0]); self.goto_y(pos[1]); self.goto_z(pos[2])

_stage_instance: object | None = None

# ---------------------- Callbacks ----------------------

@app.callback(
    Output("stage-connect-status", "children"),
    Output("store-stage-ready", "data"),
    Output("stage-poll", "disabled"),
    Input("btn-stage-connect", "n_clicks"),
    State("stage-conn-type", "value"),
    State("printer-host", "value"),
    State("printer-port", "value"),
    State("printer-com", "value"),
    State("printer-baud", "value"),
)
def stage_connect(_n, conn_type, host, port, com, baud):
    global _stage_instance
    try:
        if conn_type is None:
            conn_type = "usb"
        if not _n:
            return "Click to connect…", dash.no_update, True
        if conn_type == "usb":
            if not com:
                ports = [p.device for p in serial.tools.list_ports.comports()]
                com = "COM4" if (not ports or "COM4" in ports) else (ports[0] if ports else None)
                if com is None:
                    return "Select COM port from dropdown. (no ports detected)", None
            b = int(baud) if baud else 115200
            _stage_instance = SerialStage(com_port=com, baud=b)
            return f"Stage connected via USB on {com} @ {b} baud.", {"ok": True, "type": "usb", "com": com, "baud": b}, False
        elif conn_type == "http":
            if not host or not port or Stage is None:
                return "Enter printer host/port or install HTTP support.", None
            h = host.strip()
            if not h.startswith("http://") and not h.startswith("https://"):
                h = "http://" + h
            url = f"{h}:{int(port)}/printer/info"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            _stage_instance = Stage(controller=None, printer_ip=h, port=int(port))
            return "Stage connected.", {"ok": True, "type": "http", "host": h, "port": int(port)}, False
        else:
            return "Select connection type.", None, True
    except Exception as e:
        _stage_instance = None
        msg = str(e)
        if conn_type == "usb":
            ports = [p.device for p in serial.tools.list_ports.comports()]
            msg += (" | Detected ports: " + ", ".join(ports)) if ports else " | No serial ports detected"
        return f"Stage connect failed: {msg}", None, True

@app.callback(
    Output("stage-conn-heartbeat", "children"),
    Input("stage-poll", "n_intervals"),
)
def stage_connection_indicator(_n):
    try:
        ok = _stage_instance is not None
        if ok:
            if isinstance(_stage_instance, SerialStage):
                try:
                    _stage_instance._send("M105")
                    return "Heartbeat: USB OK"
                except Exception as e:
                    return f"Heartbeat: USB write failed: {e}"
            return "Heartbeat: HTTP OK"
        return "Heartbeat: Not connected"
    except Exception as e:
        return f"Heartbeat error: {e}"

@app.callback(
    Output("pocket-1-display", "children"),
    Output("pocket-2-display", "children"),
    Input("store-pocket-1", "data"),
    Input("store-pocket-2", "data"),
)
def show_pocket_locations(p1, p2):
    def _fmt(name, data):
        if isinstance(data, dict) and all(k in data for k in ("x","y","z")):
            try:
                x = int(data.get("x",0)); y = int(data.get("y",0)); z = int(data.get("z",0))
                ts = data.get("ts", "")
                return f"{name}: x={x} µm, y={y} µm, z={z} µm" + (f" (saved {ts})" if ts else "")
            except Exception:
                pass
        return f"{name}: not set"
    return _fmt("Pocket 1", p1), _fmt("Pocket 2", p2)

@app.callback(
    Output("printer-com", "options"),
    Output("printer-com", "value"),
    Input("stage-poll", "n_intervals"),
    State("printer-com", "options"),
    State("printer-com", "value"),
)
def populate_com_dropdown(_n, current_options, current_value):
    ports = list(serial.tools.list_ports.comports())
    new_options = [{"label": f"{p.device} — {p.description}", "value": p.device} for p in ports]
    # If options unchanged, do nothing
    if isinstance(current_options, list) and current_options == new_options:
        return no_update, no_update
    # Preserve current selection if still available
    values = [opt["value"] for opt in new_options]
    new_value = current_value if current_value in values else (values[0] if values else None)
    return new_options, new_value

# Client-side: poll window.dashKeyEvent into store-key
app.clientside_callback(
    "function(n){ const ev = window.dashKeyEvent; return ev || null; }",
    Output("store-key", "data"),
    Input("key-poll", "n_intervals")
)

@app.callback(
    Output("stage-action-status", "children"),
    Output("store-key-ts", "data"),
    Output("store-pocket-1", "data"),
    Output("store-pocket-2", "data"),
    Input("store-key", "data"),
    Input("btn-stage-home", "n_clicks"),
    Input("btn-stage-level", "n_clicks"),
    Input("btn-left", "n_clicks"),
    Input("btn-right", "n_clicks"),
    Input("btn-up", "n_clicks"),
    Input("btn-down", "n_clicks"),
    Input("btn-z-up", "n_clicks"),
    Input("btn-z-down", "n_clicks"),
    Input("btn-save-pocket-1", "n_clicks"),
    Input("btn-save-pocket-2", "n_clicks"),
    Input("btn-goto-pocket-1", "n_clicks"),
    Input("btn-goto-pocket-2", "n_clicks"),
    Input("btn-default-cup-1", "n_clicks"),
    Input("btn-default-cup-2", "n_clicks"),
    Input("btn-start-sequence", "n_clicks"),
    State("store-key-ts", "data"),
    State("jog-um", "value"),
    State("seq-pause-sec", "value"),
    State("store-pocket-1", "data"),
    State("store-pocket-2", "data"),
)
def stage_actions(key_data, n_home, n_level, nleft, nright, nup, ndown, nzup, nzdown,
                  n_save_p1, n_save_p2, n_goto_p1, n_goto_p2, n_default_cup1, n_default_cup2, n_start_seq,
                  last_ts, jog_um, pause_sec, pocket1, pocket2):
    global _stage_instance
    if not _stage_instance:
        return "Stage not connected.", last_ts, dash.no_update, dash.no_update

    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update, last_ts, dash.no_update, dash.no_update
    which = ctx.triggered[0]['prop_id'].split('.')[0]

    try:
        step = int(jog_um) if jog_um is not None else 1000
    except Exception:
        step = 1000

    try:
        if which == "store-key":
            if not key_data:
                return no_update, last_ts
            ts = key_data.get("ts")
            if last_ts == ts:
                return no_update, last_ts
            key = key_data.get("key")
            shift = bool(key_data.get("shift"))
            if shift and key == "ArrowUp":
                _stage_instance.move_z(step)
                return f"Moved Z by +{step} µm.", ts, dash.no_update, dash.no_update
            if shift and key == "ArrowDown":
                _stage_instance.move_z(-step)
                return f"Moved Z by -{step} µm.", ts, dash.no_update, dash.no_update
            if key == "ArrowLeft":
                _stage_instance.move_x(-step)
                return f"Moved X by -{step} µm.", ts, dash.no_update, dash.no_update
            if key == "ArrowRight":
                _stage_instance.move_x(step)
                return f"Moved X by +{step} µm.", ts, dash.no_update, dash.no_update
            if key == "ArrowUp":
                _stage_instance.move_y(step)
                return f"Moved Y by +{step} µm.", ts, dash.no_update, dash.no_update
            if key == "ArrowDown":
                _stage_instance.move_y(-step)
                return f"Moved Y by -{step} µm.", ts, dash.no_update, dash.no_update
            return no_update, last_ts, dash.no_update, dash.no_update

        if which == "btn-stage-home":
            _stage_instance.move_home((0, 0, 0))
            return "Homing sent (G28).", last_ts, dash.no_update, dash.no_update
        if which == "btn-stage-level":
            _stage_instance.auto_level()
            return "Auto level sent (G29).", last_ts, dash.no_update, dash.no_update
        if which == "btn-left":
            _stage_instance.move_x(-step)
            return f"Moved X by -{step} µm.", last_ts, dash.no_update, dash.no_update
        if which == "btn-right":
            _stage_instance.move_x(step)
            return f"Moved X by +{step} µm.", last_ts, dash.no_update, dash.no_update
        if which == "btn-up":
            _stage_instance.move_y(step)
            return f"Moved Y by +{step} µm.", last_ts, dash.no_update, dash.no_update
        if which == "btn-down":
            _stage_instance.move_y(-step)
            return f"Moved Y by -{step} µm.", last_ts, dash.no_update, dash.no_update
        if which == "btn-z-down":
            _stage_instance.move_z(-step)
            return f"Moved Z by -{step} µm.", last_ts, dash.no_update, dash.no_update
        if which == "btn-z-up":
            _stage_instance.move_z(step)
            return f"Moved Z by +{step} µm.", last_ts, dash.no_update, dash.no_update

        if which == "btn-save-pocket-1":
            data = {"x": _stage_instance.x, "y": _stage_instance.y, "z": _stage_instance.z, "ts": ts_utc()}
            return "Saved Cup 1 location.", last_ts, data, dash.no_update
        if which == "btn-save-pocket-2":
            data = {"x": _stage_instance.x, "y": _stage_instance.y, "z": _stage_instance.z, "ts": ts_utc()}
            return "Saved Cup 2 location.", last_ts, dash.no_update, data
        if which == "btn-goto-pocket-1":
            if isinstance(pocket1, dict):
                _stage_instance.goto((int(pocket1.get("x",0)), int(pocket1.get("y",0)), int(pocket1.get("z",0))))
                return "Moved to Cup 1.", last_ts, dash.no_update, dash.no_update
            return "Cup 1 not set.", last_ts, dash.no_update, dash.no_update
        if which == "btn-goto-pocket-2":
            if isinstance(pocket2, dict):
                _stage_instance.goto((int(pocket2.get("x",0)), int(pocket2.get("y",0)), int(pocket2.get("z",0))))
                return "Moved to Cup 2.", last_ts, dash.no_update, dash.no_update
            return "Cup 2 not set.", last_ts, dash.no_update, dash.no_update
        if which == "btn-default-cup-1":
            data = {"x": 86000, "y": 148000, "z": 0, "ts": ts_utc()}
            return "Default set for Cup 1.", last_ts, data, dash.no_update
        if which == "btn-default-cup-2":
            data = {"x": 133000, "y": 70000, "z": 0, "ts": ts_utc()}
            return "Default set for Cup 2.", last_ts, dash.no_update, data
        if which == "btn-start-sequence":
            # Start from Cup 1 if set, move 10 mm per step
            step = 10000
            try:
                p = float(pause_sec) if pause_sec is not None else 2.0
                if p < 0:
                    p = 0.0
            except Exception:
                p = 2.0
            # Sequence: down, down, right, up, up, left
            try:
                if isinstance(pocket1, dict):
                    _stage_instance.goto((int(pocket1.get("x",0)), int(pocket1.get("y",0)), int(pocket1.get("z",0))))
                    time.sleep(p)
                _stage_instance.move_y(-step); time.sleep(p)
                _stage_instance.move_y(-step); time.sleep(p)
                _stage_instance.move_x(step); time.sleep(p)
                _stage_instance.move_y(step); time.sleep(p)
                _stage_instance.move_y(step); time.sleep(p)
                _stage_instance.move_x(-step)
                return "Sequence complete.", last_ts, dash.no_update, dash.no_update
            except Exception as e:
                return f"Sequence failed: {e}", last_ts, dash.no_update, dash.no_update
        return no_update, last_ts, dash.no_update, dash.no_update
    except Exception as e:
        return f"Stage action failed: {e}", last_ts, dash.no_update, dash.no_update

# ---------------------- Run ----------------------

if __name__ == "__main__":
    import threading
    import webbrowser

    HOST = "127.0.0.1"
    PORT = 8070

    def _open():
        # open a new tab reliably on Windows
        webbrowser.open(f"http://{HOST}:{PORT}/", new=2, autoraise=True)

    # Give Flask a moment to start before opening the tab
    threading.Timer(1.2, _open).start()

    app.run_server(debug=False, host=HOST, port=PORT)

