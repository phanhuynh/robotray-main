import plotly.graph_objects as go
from collections import defaultdict
import glob
import csv

print("Loading data for all sample types...", flush=True)

# Define the sample types and their colors
sample_configs = {
    'MiningHighVoltage': '#1f77b4',
    'MiningLowVoltage': '#ff7f0e',
    'SoilHighVoltage': '#2ca02c',
    'SoilMidVoltage': '#d62728',
    'SoilLowVoltage': '#9467bd'
}

# Create figure with secondary y axis
fig = go.Figure()

for sample_type, color in sample_configs.items():
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
            with open(filepath, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    energy = float(row['Energy (keV)'])
                    intensity = float(row['Intensity (CPS)'])
                    energy_intensity[energy].append(intensity)
        except Exception as e:
            print(f"  Error reading {filepath}: {e}", flush=True)
            continue
    
    # Calculate averages
    energies = sorted(energy_intensity.keys())
    averages = [sum(energy_intensity[e]) / len(energy_intensity[e]) for e in energies]
    
    # Apply 21-point moving average smoothing
    window_size = 21
    smoothed = []
    for i in range(len(averages)):
        start = max(0, i - window_size // 2)
        end = min(len(averages), i + window_size // 2 + 1)
        smoothed.append(sum(averages[start:end]) / (end - start))
    
    print(f"  Average intensity range: {min(smoothed):.6f} to {max(smoothed):.6f} CPS", flush=True)
    
    # Add trace
    fig.add_trace(
        go.Scatter(
            x=energies,
            y=smoothed,
            mode='lines',
            name=sample_type,
            line=dict(color=color, width=2),
            hovertemplate=f'{sample_type}<br>Energy: %{{x:.2f}} keV<br>Intensity: %{{y:.2f}} CPS<extra></extra>'
        )
    )

# Update layout
fig.update_layout(
    title="Energy Spectra - All Sample Types",
    xaxis_title="Energy (keV)",
    yaxis_title="Intensity (CPS)",
    hovermode='x unified',
    width=1600,
    height=700,
    font=dict(size=12),
    plot_bgcolor='rgba(240,240,240,0.5)',
    showlegend=True,
    legend=dict(
        yanchor="top",
        y=0.99,
        xanchor="left",
        x=0.01,
        bgcolor="rgba(255,255,255,0.8)"
    )
)

print("Writing HTML file...", flush=True)
fig.write_html("all_spectra_combined.html")
print("Plot saved: all_spectra_combined.html", flush=True)
print("Done!", flush=True)
