import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from collections import defaultdict
import glob
from pathlib import Path

# Define the sample types and their colors
sample_configs = {
    'MiningHighVoltage': '#1f77b4',
    'MiningLowVoltage': '#ff7f0e',
    'SoilHighVoltage': '#2ca02c',
    'SoilMidVoltage': '#d62728',
    'SoilLowVoltage': '#9467bd'
}

print("Loading data for all sample types...", flush=True)

# Create subplots (1 row, 5 columns)
fig = make_subplots(
    rows=1, cols=5,
    subplot_titles=list(sample_configs.keys()),
    specs=[[{'secondary_y': False}] * 5]
)

max_intensity = 0

for col_idx, (sample_type, color) in enumerate(sample_configs.items(), 1):
    print(f"Processing {sample_type}...", flush=True)
    
    # Find all CSV files for this sample type
    pattern = f"sample_outputs/*{sample_type}*.csv"
    files = sorted(glob.glob(pattern))
    print(f"  Found {len(files)} files", flush=True)
    
    if not files:
        continue
    
    # Aggregate data
    energy_intensity = defaultdict(list)
    
    for filepath in files:
        try:
            df = pd.read_csv(filepath)
            for _, row in df.iterrows():
                energy = float(row['Energy (keV)'])
                intensity = float(row['Intensity (CPS)'])
                energy_intensity[energy].append(intensity)
        except Exception as e:
            print(f"  Error reading {filepath}: {e}", flush=True)
            continue
    
    # Calculate averages
    energies = sorted(energy_intensity.keys())
    averages = [sum(energy_intensity[e]) / len(energy_intensity[e]) for e in energies]
    max_intensity = max(max_intensity, max(averages))
    
    # Apply 21-point moving average smoothing
    window_size = 21
    smoothed = []
    for i in range(len(averages)):
        start = max(0, i - window_size // 2)
        end = min(len(averages), i + window_size // 2 + 1)
        smoothed.append(sum(averages[start:end]) / (end - start))
    
    print(f"  Average intensity range: {min(smoothed):.6f} to {max(smoothed):.6f} CPS", flush=True)
    
    # Add trace to subplot
    fig.add_trace(
        go.Scatter(
            x=energies,
            y=smoothed,
            mode='lines',
            name=sample_type,
            line=dict(color=color, width=2),
            hovertemplate=f'{sample_type}<br>Energy: %{{x:.2f}} keV<br>Intensity: %{{y:.2f}} CPS<extra></extra>'
        ),
        row=1, col=col_idx
    )

# Update layout
fig.update_layout(
    title_text="All Sample Types - Smoothed Average Energy Spectra",
    height=600,
    width=2000,
    showlegend=True,
    hovermode='x unified',
    font=dict(size=10)
)

# Update x-axes
fig.update_xaxes(title_text="Energy (keV)", row=1, col=1)
fig.update_xaxes(title_text="Energy (keV)", row=1, col=2)
fig.update_xaxes(title_text="Energy (keV)", row=1, col=3)
fig.update_xaxes(title_text="Energy (keV)", row=1, col=4)
fig.update_xaxes(title_text="Energy (keV)", row=1, col=5)

# Update y-axes
fig.update_yaxes(title_text="Intensity (CPS)", row=1, col=1)
fig.update_yaxes(title_text="Intensity (CPS)", row=1, col=2)
fig.update_yaxes(title_text="Intensity (CPS)", row=1, col=3)
fig.update_yaxes(title_text="Intensity (CPS)", row=1, col=4)
fig.update_yaxes(title_text="Intensity (CPS)", row=1, col=5)

print("Writing HTML file...", flush=True)
fig.write_html("all_voltage_types_comparison.html")
print("Plot saved: all_voltage_types_comparison.html", flush=True)
print("Done!", flush=True)
