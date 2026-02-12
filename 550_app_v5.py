# SciAps X-550 Basic Dashboard
# ------------------------------------------------------
# Core controls: Connect/Identify • Live Status • Mode selector • Analyze (final/all) • Abort • Export ZIP

from __future__ import annotations
import io, json, zipfile, os, socket, webbrowser
from datetime import datetime, timezone
from typing import Any, Dict
import requests, pandas as pd
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
    html.Details([
        html.Summary("Connection tips (from SciAps RemoteService)"),
        html.Ul([
            html.Li("Keep the RemoteService screen visible on the analyzer while using the API."),
            html.Li("RemoteService listens on the network configured in Android Settings; use the IP shown there (enable 'Show IP')."),
            html.Li(["USB tethering is simplest: turn Wi‑Fi off and plug USB; IP is ", html.Code("192.168.42.129"), "."]),
            html.Li(["Wi‑Fi client: join an access point and use the IP shown on the RemoteService screen."]),
            html.Li([html.Strong("Note:"), " Android portable hotspot showing ", html.Code("192.168.43.1"), " is deprecated on latest EU firmware."]),
        ], style={"margin": "6px 0"})
    ], open=False),
    html.Div([
        html.Label("Analyzer IP"), dcc.Input(id="ip", value="192.168.42.129", type="text", style={"width": "200px"}),
        html.Label("Port (scan from)"), dcc.Input(id="port", value="8080", type="number", style={"width": "110px"}),
        html.Button("USB 192.168.42.129", id="btn-fill-usb"),
        html.Button("Hotspot 192.168.43.1", id="btn-fill-hotspot"),
        html.Button("Connect", id="btn-connect"), html.Span(id="connect-status", style={"marginLeft": "10px"}),
    ], style={"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap"}),

    html.Div(id="live-status", style={"marginTop": "6px", "fontSize": "14px"}),
    dcc.Interval(id="status-timer", interval=5000, n_intervals=0, disabled=True),

    html.Hr(),

    # Beam timing editor
    html.Div([
        html.H4("Beam Timing (seconds per beam)"),
        html.Div([
            html.Label("Seconds per beam"),
            dcc.Input(id="beam-sec", type="number", min=1, step=1, value=30, style={"width": "100px"}),
            html.Button("Load Beams", id="btn-load-beams"),
            html.Span(id="beam-info", style={"marginLeft": "8px"}),
            html.Button("Apply Beam Times", id="btn-apply-beams", style={"marginLeft": "10px"}),
            html.Span(id="beam-apply-status", style={"marginLeft": "8px", "fontStyle": "italic"}),
        ], style={"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap"}),
    ]),

    html.Hr(),

    html.Div([
        html.Label("Mode"), dcc.Dropdown(id="mode", options=[], placeholder="(connect to load modes)", style={"width": "320px"}),
        dcc.RadioItems(id="result-kind", options=[{"label": "Final", "value": "final"}, {"label": "All shots", "value": "all"}], value="final", inline=True, style={"marginLeft": "10px"}),
        html.Button("Analyze (shoot)", id="btn-analyze", n_clicks=0, style={"marginLeft": "10px"}),
        html.Button("Abort (STOP)", id="btn-abort", n_clicks=0, style={"marginLeft": "6px", "background": "#b00020", "color": "white"}),
        html.Label("Save folder"), dcc.Input(id="save-folder", type="text", value=os.path.join(os.getcwd(), "x550_runs"), style={"width": "34ch"}),
        html.Button("Save Result", id="btn-save", n_clicks=0, style={"marginLeft": "10px"}),
        html.Span(id="save-status", style={"marginLeft": "8px", "fontStyle": "italic"}),
    ], style={"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap"}),

    html.Div([
        html.Label("Camera"),
        dcc.Dropdown(
            id="camera-id",
            options=[
                {"label": "Sample (micro)", "value": "sample"},
                {"label": "Full view (macro)", "value": "fullview"}
            ],
            value="sample",
            clearable=False,
            style={"width": "220px"}
        ),
        html.Button("📸 Take Photo", id="btn-photo", n_clicks=0),
    ], style={"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap"}),

    html.Img(id="photo-display",
            style={"maxWidth": "100%", "marginTop": "10px", "border": "1px solid #ccc"}),


    html.Pre(id="result-summary", style={"whiteSpace": "pre-wrap", "marginTop": "10px"}),
    dcc.Graph(id="spectrum-graph"),

    dcc.Store(id="store-base"),
    dcc.Store(id="store-modes"),
    dcc.Store(id="store-latest"),
    dcc.Download(id="download-zip"),
    dcc.Store(id="store-acq"),
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
