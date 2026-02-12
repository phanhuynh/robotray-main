import pandas as pd
import glob
import os
import webbrowser
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def select_last_150(pattern, label):
    all_files = glob.glob(pattern)
    all_files.sort(key=os.path.getmtime)
    files = all_files[-150:]

    print(f"Found {len(all_files)} total {label} files")
    print("Using the last 150 files by date")
    print("First 5 of selected files:")
    for f in files[:5]:
        print(f"  {os.path.basename(f)}")
    print("Last 5 of selected files:")
    for f in files[-5:]:
        print(f"  {os.path.basename(f)}")

    return files


def add_traces(fig, files, row, col, color):
    for file in files:
        df = pd.read_csv(file)
        fig.add_trace(
            go.Scattergl(
                x=df['Energy (keV)'],
                y=df['Intensity (CPS)'],
                mode='lines',
                line=dict(width=1, color=color),
                opacity=0.4,
                showlegend=False,
            ),
            row=row,
            col=col,
        )


files_mining_high = select_last_150(
    "sample_outputs/*MiningHighVoltage*.csv",
    "MiningHighVoltage"
)
files_mining_low = select_last_150(
    "sample_outputs/*MiningLowVoltage*.csv",
    "MiningLowVoltage"
)
files_soil_high = select_last_150(
    "sample_outputs/*SoilHighVoltage*.csv",
    "SoilHighVoltage"
)
files_soil_mid = select_last_150(
    "sample_outputs/*SoilMidVoltage*.csv",
    "SoilMidVoltage"
)
files_soil_low = select_last_150(
    "sample_outputs/*SoilLowVoltage*.csv",
    "SoilLowVoltage"
)

fig = make_subplots(
    rows=3,
    cols=2,
    subplot_titles=(
        "MiningHighVoltage (Last 150)",
        "MiningLowVoltage (Last 150)",
        "SoilHighVoltage (Last 150)",
        "SoilMidVoltage (Last 150)",
        "SoilLowVoltage (Last 150)",
        "",
    ),
)

palette = {
    "mining_high": "#e6550d",
    "mining_low": "#a63603",
    "soil_high": "#1f78b4",
    "soil_mid": "#33a02c",
    "soil_low": "#6a3d9a",
}

add_traces(fig, files_mining_high, row=1, col=1, color=palette["mining_high"])
add_traces(fig, files_mining_low, row=1, col=2, color=palette["mining_low"])
add_traces(fig, files_soil_high, row=2, col=1, color=palette["soil_high"])
add_traces(fig, files_soil_mid, row=2, col=2, color=palette["soil_mid"])
add_traces(fig, files_soil_low, row=3, col=1, color=palette["soil_low"])

fig.update_xaxes(title_text="Energy (keV)")
fig.update_yaxes(title_text="Intensity (CPS)")
fig.update_layout(
    title="Energy vs Intensity - Last 150 Files by Date",
    height=1200,
    width=1600,
)

os.makedirs("plots", exist_ok=True)
output_path = os.path.abspath("plots/energy_intensity_last150.html")
fig.write_html(output_path)
print(f"Saved interactive plot to: {output_path}")
webbrowser.open(f"file:///{output_path}")
