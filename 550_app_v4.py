# SciAps X-550 Basic Dashboard
# ------------------------------------------------------
# Core controls: Connect/Identify • Live Status • Mode selector • Analyze (final/all) • Abort • Export ZIP

from __future__ import annotations
import io, json, zipfile, os, socket, webbrowser
import time
from datetime import datetime, timezone
from typing import Any, Dict
import requests, pandas as pd
# Ensure we can import local 'sashimi' from the workspace 'particle-scanner' folder
import sys
_ps_path = os.path.join(os.getcwd(), "particle-scanner")
if _ps_path not in sys.path:
    sys.path.append(_ps_path)
from sashimi.stage import Stage
import serial
import serial.tools.list_ports
import plotly.graph_objs as go
import dash
from dash import Dash, dcc, html, Input, Output, State, no_update
from dash.exceptions import PreventUpdate  # add this near your other imports


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

def base_url(ip: str, port: int) -> str:
    return f"http://{ip}:{port}/api/v2"

def api_get(url, **kw):
    r = requests.get(url, timeout=30, **kw)
    r.raise_for_status()
    return r.json() if r.headers.get("Content-Type", "").startswith("application/json") else r.content

def api_post(url, data: Dict[str, Any] | None = None, params: Dict[str, Any] | None = None, **kw):
    r = requests.post(url, params=params or {}, json=data or {}, timeout=kw.get("timeout", 600))
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        msg = r.text.strip()
        raise requests.HTTPError(f"{e} | server says: {msg}")
    return r.json()

def api_put(url, data: Dict[str, Any] | None = None, params: Dict[str, Any] | None = None, **kw):
    r = requests.put(url, params=params or {}, json=data or {}, timeout=kw.get("timeout", 60))
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        msg = r.text.strip()
        raise requests.HTTPError(f"{e} | server says: {msg}")
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
            @app.callback(
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
                State("store-stage-ready", "data"),
                prevent_initial_call=True)
            def stage_actions_combined(key_data, n_home, n_level, nleft, nright, nup, ndown, nzup, nzdown, last_ts, jog_um, ready):
                global _stage_instance
                if not ready or not _stage_instance:
                    return no_update, last_ts

                # Determine what triggered
                ctx = dash.callback_context
                if not ctx.triggered:
                    return no_update, last_ts
                which = ctx.triggered[0]['prop_id'].split('.')[0]

                # Jog step
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

                    # Button actions
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

    # Arrow controls for XY and Z
    html.Div([
        html.Div([
            html.Button("↑", id="btn-up", style={"width":"48px","height":"48px"}),
            html.Div([
                html.Button("←", id="btn-left", style={"width":"48px","height":"48px"}),
                html.Button("→", id="btn-right", style={"width":"48px","height":"48px","marginLeft":"8px"}),
            ], style={"display":"flex","gap":"8px","justifyContent":"center","marginTop":"8px"}),
            html.Button("↓", id="btn-down", style={"width":"48px","height":"48px","marginTop":"8px"}),
        ], style={"display":"flex","flexDirection":"column","alignItems":"center","marginRight":"24px"}),
        html.Div([
            html.Button("Z+", id="btn-z-up", style={"width":"64px","height":"48px"}),
            html.Button("Z-", id="btn-z-down", style={"width":"64px","height":"48px","marginTop":"8px"}),
        ], style={"display":"flex","flexDirection":"column","alignItems":"center"}),
        html.Span(id="stage-action-status", style={"marginLeft":"16px","fontStyle":"italic","alignSelf":"center"}),
    ], style={"display":"flex","alignItems":"flex-start","flexWrap":"wrap","marginTop":"8px"}),
])

# ---------------------- Callbacks ----------------------

# Beam helpers
def _count_beams(cfg: Dict[str, Any]) -> int:
    if not isinstance(cfg, dict):
        return 0
    # Newer/minimal schema: arrays at the top level
    if isinstance(cfg.get("beamTimes"), list):
        return len(cfg["beamTimes"])
    # Classic nested schema
    if isinstance(cfg.get("beams"), list):
        return len(cfg["beams"])
    for v in cfg.values():
        if isinstance(v, dict):
            n = _count_beams(v)
            if n:
                return n
    return 0
    if isinstance(cfg.get("beams"), list):
        return len(cfg["beams"])
    for v in cfg.values():
        if isinstance(v, dict):
            n = _count_beams(v)
            if n:
                return n
    return 0

_DURATION_KEYS = {"duration", "durationSec", "durationSecs", "durationSeconds", "testTimeSeconds"}

def _set_beam_durations(cfg: Any, dur: int):
    # dur is in SECONDS from the UI
    if isinstance(cfg, dict):
        # Minimal schema: list of beamTimes in milliseconds
        if isinstance(cfg.get("beamTimes"), list):
            ms = max(1, int(round(dur * 1000)))
            cfg["beamTimes"] = [ms for _ in cfg["beamTimes"]]
        # Classic schema
        if isinstance(cfg.get("beams"), list):
            for b in cfg["beams"]:
                if isinstance(b, dict):
                    for k in list(b.keys()):
                        if k in _DURATION_KEYS or k.lower() in {s.lower() for s in _DURATION_KEYS}:
                            b[k] = dur
                        elif isinstance(b[k], (dict, list)):
                            _set_beam_durations(b[k], dur)
        for k, v in cfg.items():
            if isinstance(v, (dict, list)):
                _set_beam_durations(v, dur)
    elif isinstance(cfg, list):
        for it in cfg:
            _set_beam_durations(it, dur)

# Load current acquisition parameters for selected mode
@app.callback(
    Output("beam-info", "children"), Output("store-acq", "data"),
    Input("btn-load-beams", "n_clicks"), State("store-base", "data"), State("mode", "value"),
    prevent_initial_call=True)
def load_beams(n, base, mode):
    if not base:
        return "Not connected.", None
    if not mode:
        return "Select a mode first.", None
    try:
        cfg = api_get(base + "/acquisitionParams/user", params={"mode": mode})
        # Detect minimal array schema
        if isinstance(cfg, dict) and isinstance(cfg.get("beamTimes"), list):
            times = cfg["beamTimes"]
            # Heuristic: values >= 1000 likely milliseconds
            sec_list = [ (t/1000.0 if isinstance(t,(int,float)) and t >= 1000 else float(t)) for t in times ]
            info = ", ".join(f"B{i+1}:{s:g}s" for i,s in enumerate(sec_list))
            return f"Loaded {len(times)} beam(s) for mode '{mode}'. Times: {info}", cfg
        # Fallback to classic nested counting
        n_beams = _count_beams(cfg)
        return f"Loaded {n_beams} beam(s) for mode '{mode}'.", cfg
    except Exception as e:
        return f"Load failed: {e}", None

# Apply per-beam seconds to current acquisition parameters and PUT back
@app.callback(
    Output("beam-apply-status", "children"),
    Input("btn-apply-beams", "n_clicks"), State("beam-sec", "value"), State("store-acq", "data"), State("store-base", "data"), State("mode", "value"),
    prevent_initial_call=True)
def apply_beams(_n, sec, cfg, base, mode):
    if not base or not mode:
        return "Not connected or no mode selected."
    if not isinstance(sec, (int, float)) or sec <= 0:
        return "Enter a valid seconds value (>0)."
    if not isinstance(cfg, dict):
        return "Load beams first."
    try:
        sec = float(sec)
        new_cfg = json.loads(json.dumps(cfg))  # deep copy
        if isinstance(new_cfg.get("beamTimes"), list):
            # Minimal schema: update ms directly and keep existing flags/testType
            ms = max(1, int(round(sec * 1000)))
            new_cfg["beamTimes"] = [ms for _ in new_cfg["beamTimes"]]
            api_put(base + "/acquisitionParams/user", params={"mode": mode}, data=new_cfg)
            return f"Applied {sec:g}s per beam to mode '{mode}'. (beamTimes in ms)"
        # Classic schema path
        _set_beam_durations(new_cfg, sec)
        api_put(base + "/acquisitionParams/user", params={"mode": mode}, data=new_cfg)
        return f"Applied {int(sec)}s per beam to mode '{mode}'."
    except Exception as e:
        return f"Apply failed: {e}"

@app.callback(
    Output("ip", "value"),
    Input("btn-fill-usb", "n_clicks"),
    Input("btn-fill-hotspot", "n_clicks"),
    State("ip", "value"),
    prevent_initial_call=True)
def fill_ip(n_usb, n_hot, current):
    ctx = dash.callback_context
    if not ctx.triggered:
        return current
    which = ctx.triggered[0]['prop_id'].split('.')[0]
    return "192.168.42.129" if which == "btn-fill-usb" else "192.168.43.1"

@app.callback(
    Output("connect-status", "children"),
    Output("store-base", "data"),
    Output("store-modes", "data"),
    Output("mode", "options"),
    Output("mode", "value"),
    Output("status-timer", "disabled"),
    Input("btn-connect", "n_clicks"), State("ip", "value"), State("port", "value"),
    prevent_initial_call=True)
def connect(n, ip, port):
    try:
        start = int(port) if str(port).isdigit() else 8080
        info = None; chosen = None
        for try_p in range(start, start + 10):
            for path in ("/api/v2/id", "/api/v1/id", "/api/id"):
                url = f"http://{ip}:{try_p}{path}"
                try:
                    r = requests.get(url, timeout=5)
                    r.raise_for_status()
                    if r.headers.get("Content-Type", "").startswith("application/json") or r.text.startswith("{"):
                        info = r.json(); chosen = f"http://{ip}:{try_p}" + path.rsplit("/", 1)[0]
                        break
                except Exception:
                    continue
            if chosen:
                break
        if not chosen:
            return (f"Connect failed: no API found. Make sure the analyzer shows the RemoteService screen with an IP (enable 'Show IP'), then use that IP. Searched {ip}:{start}-{start+9}", None, None, [], None, True)
        apps = info.get("apps", []) if isinstance(info, dict) else []
        options = [{"label": a, "value": a} for a in apps] if apps else []
        default_mode = options[0]["value"] if options else None
        return f"Connected: {info.get('family', 'X-550')} | Base: {chosen}", chosen, apps, options, default_mode, False
    except Exception as e:
        return f"Connect failed: {e}", None, None, [], None, True

@app.callback(
    Output("live-status", "children"),
    Input("status-timer", "n_intervals"), State("store-base", "data"),
    prevent_initial_call=True)
def poll_status(_n, base):
    if not base:
        return no_update
    try:
        s = api_get(base + "/status")

        # --- Battery (support multiple schemas) ---
        batt = None
        if isinstance(s.get("battery"), dict):
            batt = s["battery"].get("percent") or s["battery"].get("level")
        if batt is None and s.get("batteryPercent") is not None:
            batt = s.get("batteryPercent")
        if batt is None and s.get("batteryLevel") is not None:
            batt = s.get("batteryLevel")
        if batt is None and isinstance(s.get("battery"), (int, float)):
            batt = s.get("battery")
        charging = s.get("isCharging")
        batt_str = f"{batt:.0f}%" if isinstance(batt, (int, float)) else "(no batt data)"
        if charging is True:
            batt_str += " (charging)"

        # --- Temperatures ---
        temp_parts = []
        if isinstance(s.get("temperatures"), dict):
            temp_parts.extend([f"{k}:{v:.1f}°C" for k, v in s["temperatures"].items() if isinstance(v, (int, float))])
        # explicit tube/detector fields seen on some firmwares
        if isinstance(s.get("tubeTemp"), (int, float)):
            temp_parts.append(f"tube:{s['tubeTemp']:.1f}°C")
        if isinstance(s.get("detectorTemp"), (int, float)):
            temp_parts.append(f"det:{s['detectorTemp']:.1f}°C")
        if isinstance(s.get("temperature"), (int, float)):
            temp_parts.append(f"temp:{s['temperature']:.1f}°C")
        t_text = ", ".join(temp_parts) if temp_parts else "(no temp data)"

        # --- Uptime ---
        up = (
            s.get("uptimeSec") or s.get("uptimeSeconds") or s.get("upTimeSec") or s.get("upTimeSeconds") or s.get("uptime")
        )
        def _fmt_uptime(val):
            try:
                secs = int(val)
                h = secs // 3600
                m = (secs % 3600) // 60
                sec = secs % 60
                return f"{h:02d}:{m:02d}:{sec:02d}"
            except Exception:
                return None
        up_str = _fmt_uptime(up) if up is not None else None
        up_text = up_str or "(n/a)"

        # --- Beam / acquisition state ---
        beam = s.get("beamState") or s.get("beamStatus") or s.get("acquisitionState") or s.get("xrayState") or s.get("state")
        beam_text = str(beam) if beam is not None else "(unknown)"

        msg = f"Battery: {batt_str} | Temps: {t_text} | Uptime: {up_text} | Beam: {beam_text}"
        if s.get("isECalNeeded"):
            msg += " | E-Cal needed"
        return msg

    except Exception as e:
        return f"(status unavailable: {e})"

@app.callback(
    Output("result-summary", "children"), Output("spectrum-graph", "figure"), Output("store-latest", "data"),
    Input("btn-analyze", "n_clicks"), State("store-base", "data"), State("mode", "value"), State("result-kind", "value"),
    prevent_initial_call=True)
def analyze(n, base, mode, kind):
    if not base:
        return "Not connected.", go.Figure(), None
    try:
        ep = "/test/all" if kind == "all" else "/test/final"
        res = api_post(base + ep, params={"mode": mode} if mode else {})
        chem = normalize_chemistry(res)
        spectra = normalize_spectra(res)
        summary = pd.DataFrame(chem).to_string(index=False) if chem else "(no chemistry data)"
        fig = go.Figure()
        for s in spectra:
            fig.add_trace(go.Scatter(x=s['x'], y=s['y'], mode='lines', name=s['shot']))
        payload = {"ts": ts_utc(), "mode": mode or "", "result_raw": res, "chem_rows": chem, "spectra": spectra}
        return summary, fig, payload
    except Exception as e:
        return f"Run failed: {e}", go.Figure(), None

@app.callback(
    Output("download-zip", "data"), Output("save-status", "children"),
    Input("btn-save", "n_clicks"), State("store-latest", "data"), State("save-folder", "value"),
    prevent_initial_call=True)
def save_latest(_n, payload, save_dir):
    if not payload:
        return no_update, "No result in memory. Run Analyze first."
    result_raw = payload.get("result_raw", {})
    chem_rows = payload.get("chem_rows") or normalize_chemistry(result_raw) or []
    spectra = payload.get("spectra") or normalize_spectra(result_raw) or []

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as zf:
        ts = payload.get("ts", ts_utc()); mode = payload.get("mode", "mode")
        zf.writestr(f"result_{mode}_{ts}.json", json.dumps(result_raw, indent=2))
        if chem_rows:
            dfc = pd.DataFrame(chem_rows)
            zf.writestr(f"chemistry_{mode}_{ts}.csv", dfc.to_csv(index=False))
        for s in spectra:
            name = (s.get("shot") or "final").replace(" ", "_")
            dfs = pd.DataFrame({"channel": s.get("x", []), "counts": s.get("y", [])})
            zf.writestr(f"spectrum_{name}_{ts}.csv", dfs.to_csv(index=False))
    mem.seek(0)

    out_dir = save_dir or os.path.join(os.getcwd(), "x550_runs")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"sciaps_{(payload.get('mode', 'mode') or 'mode').lower()}_{payload.get('ts', ts_utc())}.zip"
    out_path = os.path.join(out_dir, fname)
    with open(out_path, 'wb') as f:
        f.write(mem.getvalue())

    return dcc.send_bytes(mem.getvalue(), filename=fname), f"Saved to: {out_path} — and download sent."

@app.callback(
    Output("photo-display", "src"),
    Input("btn-photo", "n_clicks"),
    State("store-base", "data"),
    State("camera-id", "value"),
    prevent_initial_call=True
)
def take_photo(n, base, camera_id):
    if not base:
        return no_update
    try:
        r = requests.get(f"{base}/photo", params={"cameraId": camera_id}, timeout=15)
        r.raise_for_status()
        import base64
        b64 = base64.b64encode(r.content).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        print("Photo capture failed:", e)
        return no_update


# ---------------------- Stage Controls ----------------------

# Keep a module-level reference for the Stage instance
class SerialStage:
    def __init__(self, com_port: str, baud: int = 115200):
        # Robust CH340 init: 8N1, toggle DTR/RTS, flush buffers
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
            # Some firmware require DTR/RTS toggles to start streaming
            self.ser.dtr = False
            self.ser.rts = False
            time.sleep(0.05)
            self.ser.dtr = True
            self.ser.rts = True
        except Exception:
            pass
        # Clear any bootloader text
        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception:
            pass
        # Probe firmware to ensure link is live
        self._send("M115")  # request firmware info
        # positions tracked in µm for consistency with existing UI
        self.x = 0
        self.y = 0
        self.z = 0

    def _send(self, cmd: str) -> str:
        data = (cmd.strip() + "\r\n").encode("ascii")
        self.ser.write(data)
        self.ser.flush()
        # read simple response up to newline
        resp = b""
        try:
            resp = self.ser.readline()
        except Exception:
            pass
        return resp.decode(errors="ignore")

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

@app.callback(
    Output("stage-connect-status", "children"),
    Output("store-stage-ready", "data"),
    Input("btn-stage-connect", "n_clicks"),
    State("stage-conn-type", "value"),
    State("printer-host", "value"),
    State("printer-port", "value"),
    State("printer-com", "value"),
    State("printer-baud", "value"),
    prevent_initial_call=True)
def stage_connect(_n, conn_type, host, port, com, baud):
    global _stage_instance
    try:
        print(f"[stage_connect] click={_n} type={conn_type} host={host} port={port} com={com} baud={baud}")
        if conn_type is None:
            conn_type = "usb"
        # Immediate UI feedback
        if not _n:
            return "Click to connect…", dash.no_update
        if conn_type == "usb":
            if not com:
                ports = [p.device for p in serial.tools.list_ports.comports()]
                # Fallback to COM4 if detected earlier or user reported
                fallback = "COM4" if (not ports or "COM4" in ports) else (ports[0] if ports else None)
                if fallback is None:
                    hint = " (no ports detected)"
                    return "Select COM port from dropdown." + hint, None
                com = fallback
                print(f"[stage_connect] No COM selected; using fallback {com}")
            b = int(baud) if baud else 115200
            # Show connecting status
            print("[stage_connect] Opening serial port…")
            _stage_instance = SerialStage(com_port=com, baud=b)
            print(f"[stage_connect] USB connected on {com} @ {b}")
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
            print(f"[stage_connect] HTTP connected to {h}:{int(port)}")
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
        print(f"[stage_connect] FAILED: {msg}")
        return f"Stage connect failed: {msg}", None

# Continuously reflect connection state in a heartbeat label
@app.callback(
    Output("stage-conn-heartbeat", "children"),
    Input("stage-poll", "n_intervals"),
)
def stage_connection_indicator(_n):
    try:
        # Update COM dropdown options
        ports = [
            {"label": f"{p.device} — {p.description}", "value": p.device}
            for p in serial.tools.list_ports.comports()
        ]
        # Send options to component via clientside callback (add below)
        ok = _stage_instance is not None
        if ok:
            # Try a lightweight NO-OP write on serial to ensure port is open
            if isinstance(_stage_instance, SerialStage):
                try:
                    _stage_instance._send("M105")  # temperature query, safe
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
    prevent_initial_call=False)
def populate_com_dropdown(_n):
    ports = list(serial.tools.list_ports.comports())
    options = [{"label": f"{p.device} — {p.description}", "value": p.device} for p in ports]
    value = options[0]["value"] if options else None
    return options, value

# Key polling: clientside reads window.dashKeyEvent and updates store
app.clientside_callback(
    "function(n){\n      const ev = window.dashKeyEvent;\n      return ev || null;\n    }",
    Output("store-key", "data"),
    Input("key-poll", "n_intervals")
)


def stage_key_actions(key_data, last_ts, jog_um, ready):
    global _stage_instance
    if not ready or not _stage_instance:
        return no_update, last_ts
    if not key_data:
        return no_update, last_ts
    ts = key_data.get("ts")
    if last_ts == ts:
        return no_update, last_ts
    step = 1000
    try:
        if jog_um is not None:
            step = int(jog_um)
    except Exception:
        pass
    key = key_data.get("key")
    shift = bool(key_data.get("shift"))
    # Shift+ArrowUp/Down for Z, plain arrows for XY
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


def stage_actions(n_home, n_level, nleft, nright, nup, ndown, nzup, nzdown, jog_um, ready):
    global _stage_instance
    if not ready or not _stage_instance:
        return "Stage not connected."
    try:
        # Determine which button fired
        ctx = dash.callback_context
        if not ctx.triggered:
            return no_update
        which = ctx.triggered[0]['prop_id'].split('.')[0]
        if which == "btn-stage-home":
            _stage_instance.move_home((0, 0, 0))
            return "Homing sent (G28)."
        if which == "btn-stage-level":
            _stage_instance.auto_level()
            return "Auto level sent (G29)."
        # Jogging
        try:
            step = int(jog_um) if jog_um is not None else 1000
        except Exception:
            step = 1000
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

@app.callback(
    Output("stage-action-status", "children"),
    Output("store-key-ts", "data"),
    Input("store-key", "data"),               # keyboard
    Input("btn-stage-home", "n_clicks"),      # buttons below
    Input("btn-stage-level", "n_clicks"),
    Input("btn-left", "n_clicks"),
    Input("btn-right", "n_clicks"),
    Input("btn-up", "n_clicks"),
    Input("btn-down", "n_clicks"),
    Input("btn-z-up", "n_clicks"),
    Input("btn-z-down", "n_clicks"),
    State("jog-um", "value"),
    State("store-stage-ready", "data"),
    State("store-key-ts", "data"),
    prevent_initial_call=True,
)
def stage_actions_combined(
    key_data,
    n_home, n_level, nleft, nright, nup, ndown, nzup, nzdown,
    jog_um, ready, last_ts
):
    global _stage_instance

    # No stage connection yet
    if not ready or not _stage_instance:
        return "Stage not connected.", last_ts

    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate

    which = ctx.triggered[0]["prop_id"].split(".")[0]

    # ---------------- Keyboard arrows ----------------
    if which == "store-key":
        if not key_data:
            raise PreventUpdate

        ts = key_data.get("ts")
        if ts is None or ts == last_ts:
            # already handled this keystroke
            raise PreventUpdate

        # step size from UI
        step = 1000
        try:
            if jog_um is not None:
                step = int(jog_um)
        except Exception:
            pass

        key = key_data.get("key")
        shift = bool(key_data.get("shift"))

        # Shift+ArrowUp/Down for Z
        if shift and key == "ArrowUp":
            _stage_instance.move_z(step)
            return f"Moved Z by +{step} µm.", ts
        if shift and key == "ArrowDown":
            _stage_instance.move_z(-step)
            return f"Moved Z by -{step} µm.", ts

        # plain arrows for XY
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

        # Unhandled key: no update
        raise PreventUpdate

    # ---------------- Button actions ----------------
    # Determine jog step
    try:
        step = int(jog_um) if jog_um is not None else 1000
    except Exception:
        step = 1000

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

    if which == "btn-z-up":
        _stage_instance.move_z(step)
        return f"Moved Z by +{step} µm.", last_ts

    if which == "btn-z-down":
        _stage_instance.move_z(-step)
        return f"Moved Z by -{step} µm.", last_ts

    # Fallback
    raise PreventUpdate


if __name__ == '__main__':
    import threading, time

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
        webbrowser.open(url)

    port = find_open_port()
    url = f"http://127.0.0.1:{port}"
    print(f"Starting server on {url}")
    threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()
    app.run(debug=False, port=port, host="127.0.0.1", use_reloader=False)
