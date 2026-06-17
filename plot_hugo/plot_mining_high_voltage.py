#!/usr/bin/env python3
"""
Plot only MiningHighVoltage files from sample_outputs
"""
import os
import glob
import csv

print("Loading MiningHighVoltage data from sample_outputs...")

# Find only MiningHighVoltage CSV files
csv_files = sorted(glob.glob('sample_outputs/*MiningHighVoltage*.csv'))
print(f"Found {len(csv_files)} MiningHighVoltage files")

if not csv_files:
    print("No MiningHighVoltage files found!")
    exit(1)

# Read and aggregate data
data_by_sample = {}

for csv_file in csv_files:
    filename = os.path.basename(csv_file)
    energy = []
    intensity = []
    
    try:
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    energy.append(float(row['Energy (keV)']))
                    intensity.append(float(row['Intensity (CPS)']))
                except:
                    pass
        
        if energy and intensity:
            data_by_sample[filename] = (energy, intensity)
            print(f"  Loaded: {filename}")
    except Exception as e:
        print(f"  Error loading {filename}: {e}")

print(f"\nSuccessfully loaded {len(data_by_sample)} files")

# Create plot with Plotly
try:
    import plotly.graph_objects as go
    
    print("Creating Plotly visualization...")
    
    fig = go.Figure()
    
    # Add each file as a trace
    for filename, (energy, intensity) in sorted(data_by_sample.items()):
        fig.add_trace(go.Scatter(
            x=energy,
            y=intensity,
            mode='lines',
            name=filename.replace('_nephe.csv', ''),
            showlegend=False,
            hovertemplate='<b>%{fullData.name}</b><br>Energy: %{x:.2f} keV<br>Intensity: %{y:.4f} CPS<extra></extra>'
        ))
    
    # Update layout
    fig.update_layout(
        title=f'Mining High Voltage - Energy vs Intensity ({len(data_by_sample)} files)',
        xaxis_title='Energy (keV)',
        yaxis_title='Intensity (CPS)',
        hovermode='x unified',
        height=700,
        template='plotly_white',
        font=dict(size=12)
    )
    
    # Save as HTML
    output_file = 'mining_high_voltage_plot.html'
    fig.write_html(output_file)
    print(f"\nPlot saved: {output_file}")
    print(f"Open this file in your browser to view the interactive plot!")
    
except ImportError:
    print("Could not import plotly")
except Exception as e:
    print(f"Error creating plot: {e}")
    import traceback
    traceback.print_exc()

print("\nDone!")
