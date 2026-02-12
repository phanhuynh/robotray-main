# SciAps X-550 Basic Dashboard (Fixed)
# ------------------------------------------------------

from __future__ import annotations
import io, json, zipfile, os, socket, webbrowser, time
import threading
from datetime import datetime, timezone
from typing import Any, Dict
import requests, pandas as pd
import sys
_ps_path = os.path.join(os.getcwd(), "particle-scanner")
if _ps_path not in sys.path:
    sys.path.append(_ps_path)
from sashimi.stage import Stage
import serial, serial.tools.list_ports
import plotly.graph_objs as go
import dash
from dash import Dash, dcc, html, Input, Output, State, no_update

APP_TITLE = "SciAps X-550 Basic"
DEFAULT_PORT_START = 8070

# ---------------------- Helpers ----------------------

def ts_utc():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def find_open_port(start_port=DEFAULT_PORT_START):
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

def api_get(url, **kw):
    r = requests.get(url, timeout=30, **kw)
    r.raise_for_status()
    return r.json() if r.headers.get("Content-Type", "").startswith("application/json") else r.content

def api_post(url, data: Dict[str, Any] | None = None, params: Dict[str, Any] | None = None, **kw):
    r = requests.post(url, params=params or {}, json=data or {}, timeout=kw.get("timeout", 600))
    r.raise_for_status()
    return r.json()

def api_put(url, data: Dict[str, Any] | None = None, params: Dict[str, Any] | None = None, **kw):
    r = requests.put(url, params=params or {}, json=data or {}, timeout=kw.get("timeout", 60))
    r.raise_for_status()
    return r.json() if r.headers.get("Content-Type", "").startswith("application/json") else r.text

def normalize_chemistry(result_json: Dict[str, Any]):
    rows = []
    td = result_json.get("testData")
    if isinstance(td, dict) and isinstance(td.get("chemistry"), list):
        symbols = [None, 'H','He','Li','Be','B','C','N','O','F','Ne','Na','Mg','Al','Si','P','S','Cl','Ar',
                   'K','Ca','Sc','Ti','V','Cr','Mn','Fe','Co','Ni','Cu','Zn','Ga','Ge','As','Se','Br','Kr',
                   'Rb','Sr','Y','Zr','Nb','Mo','Tc','Ru','Rh','Pd','Ag','Cd','In','Sn','Sb','Te','I','Xe']
        for it in td["chemistry"]:
            z = it.get("atomicNumber")
            elem = symbols[z] if isinstance(z, int) and 0 < z < len(symbols) else f"Z{z}"
            val = it.get("percent")
            if elem and val is not None:
                rows.append({"analyte": elem, "value": val, "units": "wt%"})
        return rows
    chem = result_json.get("chemistry") or result_json.get("composition")
    if isinstance(chem, dict):
        for k, v in chem.items():
            rows.append({"analyte": k, "value": v})
    elif isinstance(chem, list):
        for it in chem:
            name = it.get("name") or it.get("analyte")
            val = it.get("value")
            rows.append({"analyte": name, "value": val})
    return rows

def normalize_spectra(result_json: Dict[str, Any]):
    spectra = []
    specs = result_json.get("spectra")
    if isinstance(specs, list):
        for i, sp in enumerate(specs, start=1):
            y = sp.get("data") or sp.get("counts")
            if not y:
                continue
            e0 = sp.get("energyOffset", 0.0)
            slope = sp.get("energySlope", 1.0)
            x = [e0 + slope * j for j in range(len(y))]
            name = sp.get("beamName") or f"beam_{i}"
            spectra.append({"shot": name, "x": x, "y": y})
    return spectra

# ---------------------- App ----------------------

app = Dash(__name__)
app.title = APP_TITLE

app.layout = html.Div([
    html.H2(APP_TITLE),
    # Needed by callbacks
    dcc.Store(id="store-stage-ready"),
    dcc.Interval(id="stage-poll", interval=1000, n_intervals=0),
    # Keyboard support state
    dcc.Store(id="store-key"),
    dcc.Store(id="store-key-ts"),
    dcc.Interval(id="key-poll", interval=200, n_intervals=0),
    html.Div([
        html.Label("Connection"),
        dcc.Dropdown(id="stage-conn-type", options=[
            {"label":"USB (Serial)", "value":"usb"},
            {"label":"Moonraker HTTP", "value":"http"}
        ], value="usb", clearable=False, style={"width":"180px"}),
        html.Label("Printer Host (http://ip)"),
        dcc.Input(id="printer-host", type="text", value="http://192.168.1.50", style={"width":"24ch"}),
        html.Label("Port"),
        dcc.Input(id="printer-port", type="number", value=7125, style={"width":"10ch"}),
        html.Label("COM Port"),
        dcc.Dropdown(id="printer-com", options=[{"label":"COM4","value":"COM4"}], value="COM4", placeholder="Select COM port", style={"width":"220px"}),
        html.Label("Baud"),
        dcc.Input(id="printer-baud", type="number", value=115200, style={"width":"10ch"}),
        html.Button("Connect Stage", id="btn-stage-connect"),
        html.Span(id="stage-connect-status", style={"marginLeft": "8px"}),
        html.Span(id="stage-conn-heartbeat", style={"marginLeft": "8px", "fontStyle":"italic", "color":"#555"}),
    ], style={"display":"flex","gap":"8px","alignItems":"center","flexWrap":"wrap"}),
    html.Div([
        html.Button("Home (G28)", id="btn-stage-home"),
        html.Button("Auto Level (G29)", id="btn-stage-level"),
        html.Label("Jog (µm)"),
        dcc.Input(id="jog-um", type="number", value=1000, min=1, step=100, style={"width":"12ch"}),
    ], style={"display":"flex","gap":"8px","alignItems":"center","flexWrap":"wrap","marginTop":"6px"}),
    html.Div([
        html.Button("←", id="btn-left"),
        html.Button("→", id="btn-right"),
        html.Button("↑", id="btn-up"),
        html.Button("↓", id="btn-down"),
        html.Button("Z+", id="btn-z-up"),
        html.Button("Z-", id="btn-z-down"),
        html.Span(id="stage-action-status", style={"marginLeft":"16px","fontStyle":"italic","alignSelf":"center"}),
    ], style={"display":"flex","gap":"8px","alignItems":"center","flexWrap":"wrap","marginTop":"8px"}),
])

# ---------------------- Stage Controls ----------------------

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
            Output("stage-action-status", "children"),
            Output("store-key-ts", "data"),
            Input("store-key", "data"),
            Input("btn-stage-home", "n_clicks"),
            Input("btn-stage-level", "n_clicks"),
            Input("btn-left", "n_clicks"),
            Input("btn-right", "n_clicks"),
            Input("btn-up", "n_clicks"),
            Input("btn-down", "n_clicks"),
            Input("btn-z-up", "n_clicks"),
            Input("btn-z-down", "n_clicks"),
            State("store-key-ts", "data"),
            State("jog-um", "value"),
        )
        def stage_actions(key_data, n_home, n_level, nleft, nright, nup, ndown, nzup, nzdown, last_ts, jog_um):

    def move_home(self, home_position=(0,0,0)):
                return "Stage not connected.", last_ts
        self.goto(home_position)
            if not ctx.triggered:
                return no_update, last_ts
            which = ctx.triggered[0]['prop_id'].split('.')[0]

    def move_x(self, distance_um: int):
        self.goto_x(self.x + distance_um)

            try:
                # Keyboard path
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
                        return f"Moved Z by +{step} µm.", ts
                    if shift and key == "ArrowDown":
                        _stage_instance.move_z(-step)
                        return f"Moved Z by -{step} µm.", ts
                    if key == "ArrowLeft":
                        _stage_instance.move_x(-step)
                        return f"Moved X by -{step} µm.", ts
                    if key == "ArrowRight":
                        _stage_instance.move_x(step)
                        return f"Moved X by +{step} µm.", ts
                    if key == "ArrowUp":
                        _stage_instance.move_y(step)
                        return f"Moved Y by +{step} µm.", ts
                    if key == "ArrowDown":
                        _stage_instance.move_y(-step)
                        return f"Moved Y by -{step} µm.", ts
                    return no_update, last_ts

                # Buttons path
                if which == "btn-stage-home":
                    _stage_instance.move_home((0, 0, 0))
                    return "Homing sent (G28).", last_ts
                if which == "btn-stage-level":
                    _stage_instance.auto_level()
                    return "Auto level sent (G29).", last_ts
                if which == "btn-left":
                    _stage_instance.move_x(-step)
                    return f"Moved X by -{step} µm.", last_ts
                if which == "btn-right":
                    _stage_instance.move_x(step)
                    return f"Moved X by +{step} µm.", last_ts
                if which == "btn-up":
                    _stage_instance.move_y(step)
                    return f"Moved Y by +{step} µm.", last_ts
                if which == "btn-down":
                    _stage_instance.move_y(-step)
                    return f"Moved Y by -{step} µm.", last_ts
                if which == "btn-z-down":
                    _stage_instance.move_z(-step)
                    return f"Moved Z by -{step} µm.", last_ts
                if which == "btn-z-up":
                    _stage_instance.move_z(step)
                    return f"Moved Z by +{step} µm.", last_ts
                return no_update, last_ts
            except Exception as e:
                return f"Stage action failed: {e}", last_ts

        # Poll the window event into a store (clientside, in-browser)
        app.clientside_callback(
            "function(n){ const ev = window.dashKeyEvent; return ev || null; }",
            Output("store-key", "data"),
            Input("key-poll", "n_intervals")
        )
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
            return "Click to connect…", dash.no_update
        if conn_type == "usb":
            if not com:
                ports = [p.device for p in serial.tools.list_ports.comports()]
                fallback = "COM4" if (not ports or "COM4" in ports) else (ports[0] if ports else None)
                if fallback is None:
                    return "Select COM port from dropdown. (no ports detected)", None
                com = fallback
            b = int(baud) if baud else 115200
            _stage_instance = SerialStage(com_port=com, baud=b)
            return f"Stage connected via USB on {com} @ {b} baud.", {"ok": True, "type": "usb", "com": com, "baud": b}
        elif conn_type == "http":
            if not host or not port:
                return "Enter printer host and port.", None
            h = host.strip()
            if not h.startswith("http://") and not h.startswith("https://"):
                h = "http://" + h
            url = f"{h}:{int(port)}/printer/info"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            _stage_instance = Stage(controller=None, printer_ip=h, port=int(port))
            return "Stage connected.", {"ok": True, "type": "http", "host": h, "port": int(port)}
        else:
            return "Select connection type.", None
    except Exception as e:
        _stage_instance = None
        msg = str(e)
        if conn_type == "usb":
            ports = [p.device for p in serial.tools.list_ports.comports()]
            if ports:
                msg += f" | Detected ports: {', '.join(ports)}"
            else:
                msg += " | No serial ports detected"
        return f"Stage connect failed: {msg}", None

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
    Output("printer-com", "options"),
    Output("printer-com", "value"),
    Input("stage-poll", "n_intervals"),
)
def populate_com_dropdown(_n):
    ports = list(serial.tools.list_ports.comports())
    options = [{"label": f"{p.device} — {p.description}", "value": p.device} for p in ports]
    value = options[0]["value"] if options else None
    return options, value

@app.callback(
    Output("stage-action-status", "children"),
    Input("btn-stage-home", "n_clicks"),
    Input("btn-stage-level", "n_clicks"),
    Input("btn-left", "n_clicks"),
    Input("btn-right", "n_clicks"),
    Input("btn-up", "n_clicks"),
    Input("btn-down", "n_clicks"),
    Input("btn-z-up", "n_clicks"),
    Input("btn-z-down", "n_clicks"),
    State("jog-um", "value"),
)
def stage_actions(n_home, n_level, nleft, nright, nup, ndown, nzup, nzdown, jog_um):
    global _stage_instance
    if not _stage_instance:
        return "Stage not connected."
    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update
    which = ctx.triggered[0]['prop_id'].split('.')[0]
    try:
        step = int(jog_um) if jog_um is not None else 1000
    except Exception:
        step = 1000
    try:
        if which == "btn-stage-home":
            _stage_instance.move_home((0, 0, 0))
            return "Homing sent (G28)."
        if which == "btn-stage-level":
            _stage_instance.auto_level()
            return "Auto level sent (G29)."
        if which == "btn-left":
            _stage_instance.move_x(-step)
            return f"Moved X by -{step} µm."
        if which == "btn-right":
            _stage_instance.move_x(step)
            return f"Moved X by +{step} µm."
        if which == "btn-up":
            _stage_instance.move_y(step)
            return f"Moved Y by +{step} µm."
        if which == "btn-down":
            _stage_instance.move_y(-step)
            return f"Moved Y by -{step} µm."
        if which == "btn-z-down":
            _stage_instance.move_z(-step)
            return f"Moved Z by -{step} µm."
        if which == "btn-z-up":
            _stage_instance.move_z(step)
            return f"Moved Z by +{step} µm."
        return no_update
    except Exception as e:
        return f"Stage action failed: {e}"

if __name__ == '__main__':
    def _open_browser_when_ready(url: str, timeout: float = 20.0):
        start = time.time()
        while time.time() - start < timeout:
            try:
                r = requests.get(url, timeout=0.5)
                if r.status_code in (200, 302, 404):
                    webbrowser.open(url)
                    return
            except Exception:
                time.sleep(0.3)
        # fallback: open anyway
        webbrowser.open(url)

    port = find_open_port()
    url = f"http://127.0.0.1:{port}"
    print(f"Starting server on {url}")
    threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()
    app.run(debug=False, port=port, host="127.0.0.1", use_reloader=False)
