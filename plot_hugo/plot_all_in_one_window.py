import csv
import glob
from collections import defaultdict

import plotly.graph_objects as go
import plotly.io as pio

SAMPLE_CONFIGS = {
    "MiningHighVoltage": "#1f77b4",
    "MiningLowVoltage": "#ff7f0e",
    "SoilHighVoltage": "#2ca02c",
    "SoilMidVoltage": "#d62728",
    "SoilLowVoltage": "#9467bd",
}


def load_smoothed_average(sample_type, window_size=21):
    pattern = f"sample_outputs/*{sample_type}*.csv"
    files = sorted(glob.glob(pattern))
    if not files:
        return [], []

    energy_intensity = defaultdict(list)
    for filepath in files:
        try:
            with open(filepath, newline="", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    energy = float(row["Energy (keV)"])
                    intensity = float(row["Intensity (CPS)"])
                    energy_intensity[energy].append(intensity)
        except Exception:
            continue

    energies = sorted(energy_intensity.keys())
    averages = [sum(energy_intensity[e]) / len(energy_intensity[e]) for e in energies]

    smoothed = []
    for i in range(len(averages)):
        start = max(0, i - window_size // 2)
        end = min(len(averages), i + window_size // 2 + 1)
        smoothed.append(sum(averages[start:end]) / (end - start))

    return energies, smoothed


def build_figure(sample_type, color):
    energies, smoothed = load_smoothed_average(sample_type)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=energies,
            y=smoothed,
            mode="lines",
            name=sample_type,
            line=dict(color=color, width=2),
            hovertemplate=(
                f"{sample_type}<br>Energy: %{{x:.2f}} keV"
                "<br>Intensity: %{y:.2f} CPS<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title=sample_type,
        xaxis_title="Energy (keV)",
        yaxis_title="Intensity (CPS)",
        margin=dict(l=50, r=20, t=40, b=45),
        height=420,
        showlegend=False,
        plot_bgcolor="rgba(255,255,255,1)",
        paper_bgcolor="rgba(255,255,255,1)",
        font=dict(size=11),
    )
    return fig


fig_html_blocks = []
for sample_type, color in SAMPLE_CONFIGS.items():
    fig = build_figure(sample_type, color)
    fig_html = pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs=False,
        config={"displayModeBar": False, "responsive": True},
    )
    fig_html_blocks.append(f"<div class=\"plot\">{fig_html}</div>")

html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>All Plots - One Window</title>
  <script src=\"https://cdn.plot.ly/plotly-latest.min.js\"></script>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: Arial, sans-serif; background: #fff; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 14px;
            padding: 14px;
            height: 100vh;
            overflow: hidden;
        }}
        .plot {{
            border: 1px solid #e0e0e0;
            padding: 8px;
            overflow: hidden;
        }}
  </style>
</head>
<body>
  <div class=\"grid\">
    {"".join(fig_html_blocks)}
  </div>
</body>
</html>
"""

with open("all_plots_one_window.html", "w", encoding="utf-8") as f:
    f.write(html)

print("Saved: all_plots_one_window.html")
