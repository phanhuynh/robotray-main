#!/usr/bin/env python3
"""
Plot average of all MiningHighVoltage files from sample_outputs
"""
import os
import glob
import csv
from collections import defaultdict

print("Loading MiningHighVoltage data from sample_outputs...")

# Find only MiningHighVoltage CSV files
csv_files = sorted(glob.glob('sample_outputs/*MiningHighVoltage*.csv'))
print(f"Found {len(csv_files)} MiningHighVoltage files")

if not csv_files:
    print("No MiningHighVoltage files found!")
    exit(1)

# Read and aggregate data
energy_intensity_map = defaultdict(list)
all_energy_values = set()

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
                    all_energy_values.add(energy)
                except:
                    pass
    except Exception as e:
        print(f"  Error loading {filename}: {e}")

print(f"Loaded {len(csv_files)} files")
print(f"Total unique energy points: {len(energy_intensity_map)}")

# Calculate averages
energy_values = sorted(energy_intensity_map.keys())
avg_intensity = [sum(energy_intensity_map[e]) / len(energy_intensity_map[e]) for e in energy_values]

print(f"Average intensity range: {min(avg_intensity):.6f} to {max(avg_intensity):.6f} CPS")

# Apply smoothing using Savitzky-Golay filter
try:
    from scipy.signal import savgol_filter
    print("Applying Savitzky-Golay smoothing...")
    # Apply savitzky-golay smoothing (window=51 points, polynomial order=3)
    smoothed_intensity = savgol_filter(avg_intensity, window_length=51, polyorder=3)
    print("Applied Savitzky-Golay smoothing")
except Exception as e:
    print(f"Could not use scipy smoothing ({e}), using simple moving average instead...")
    # Fallback: simple moving average
    window_size = 21
    smoothed_intensity = []
    for i in range(len(avg_intensity)):
        start = max(0, i - window_size // 2)
        end = min(len(avg_intensity), i + window_size // 2 + 1)
        smoothed_intensity.append(sum(avg_intensity[start:end]) / (end - start))
    print("Applied moving average smoothing")

# Create plot with Plotly
try:
    import plotly.graph_objects as go
    
    print("Creating average plot...")
    
    fig = go.Figure()
    
    # Add average curve
    fig.add_trace(go.Scatter(
        x=energy_values,
        y=smoothed_intensity,
        mode='lines',
        name='Smoothed Average',
        line=dict(color='#1f77b4', width=3),
        hovertemplate='Energy: %{x:.2f} keV<br>Smoothed Intensity: %{y:.6f} CPS<extra></extra>'
    ))
    
    # Update layout
    fig.update_layout(
        title=f'Mining High Voltage - Smoothed Average Energy vs Intensity ({len(csv_files)} files)',
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
    
    # Save as HTML
    output_file = 'mining_high_voltage_average.html'
    fig.write_html(output_file)
    print(f"\nPlot saved: {output_file}")
    
except ImportError:
    print("Could not import plotly")
except Exception as e:
    print(f"Error creating plot: {e}")
    import traceback
    traceback.print_exc()

print("Done!")
