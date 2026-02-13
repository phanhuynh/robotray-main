#!/usr/bin/env python3
"""
Plot smoothed average of all MiningLowVoltage files from sample_outputs
"""
import os
import glob
import csv
from collections import defaultdict

print("Loading MiningLowVoltage data from sample_outputs...", flush=True)

# Find only MiningLowVoltage CSV files
csv_files = sorted(glob.glob('sample_outputs/*MiningLowVoltage*.csv'))
print(f"Found {len(csv_files)} MiningLowVoltage files", flush=True)

if not csv_files:
    print("No MiningLowVoltage files found!")
    exit(1)

# Read and aggregate data
energy_intensity_map = defaultdict(list)

for csv_file in csv_files:
    filename = os.path.basename(csv_file)
    
    try:
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    energy = float(row['Energy (keV)'])
                    intensity = float(row['Intensity (CPS)'])
                    energy_intensity_map[energy].append(intensity)
                except:
                    pass
    except Exception as e:
        print(f"  Error loading {filename}: {e}", flush=True)

print(f"Loaded {len(csv_files)} files", flush=True)
print(f"Total unique energy points: {len(energy_intensity_map)}", flush=True)

# Calculate averages
print("Calculating averages...", flush=True)
energy_values = sorted(energy_intensity_map.keys())
avg_intensity = [sum(energy_intensity_map[e]) / len(energy_intensity_map[e]) for e in energy_values]

print(f"Average intensity range: {min(avg_intensity):.6f} to {max(avg_intensity):.6f} CPS", flush=True)

# Apply simple moving average smoothing
print("Applying smoothing...", flush=True)
window_size = 21
smoothed_intensity = []
for i in range(len(avg_intensity)):
    start = max(0, i - window_size // 2)
    end = min(len(avg_intensity), i + window_size // 2 + 1)
    smoothed_intensity.append(sum(avg_intensity[start:end]) / (end - start))
print("Applied moving average smoothing", flush=True)

# Create plot with Plotly
print("Creating Plotly figure...", flush=True)
try:
    import plotly.graph_objects as go
    
    fig = go.Figure()
    
    # Add smoothed curve
    fig.add_trace(go.Scatter(
        x=energy_values,
        y=smoothed_intensity,
        mode='lines',
        name='Smoothed Average',
        line=dict(color='#ff7f0e', width=3),
        hovertemplate='Energy: %{x:.2f} keV<br>Smoothed Intensity: %{y:.6f} CPS<extra></extra>'
    ))
    
    # Update layout
    fig.update_layout(
        title=f'Mining Low Voltage - Smoothed Average Energy vs Intensity ({len(csv_files)} files)',
        xaxis_title='Energy (keV)',
        yaxis_title='Smoothed Average Intensity (CPS)',
        hovermode='x unified',
        height=700,
        template='plotly_white',
        font=dict(size=12),
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.99,
            xanchor="right",
            x=0.99
        )
    )
    
    print("Writing HTML file...", flush=True)
    # Save as HTML
    output_file = 'mining_low_voltage_average.html'
    fig.write_html(output_file)
    print(f"Plot saved: {output_file}", flush=True)
    
except Exception as e:
    print(f"Error creating plot: {e}", flush=True)
    import traceback
    traceback.print_exc()

print("Done!", flush=True)
