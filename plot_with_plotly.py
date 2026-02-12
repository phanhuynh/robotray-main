#!/usr/bin/env python3
"""
Plot energy and intensity data using Plotly
"""
import os
import glob
import csv
from pathlib import Path

print("Loading data from CSV files...")

# Find CSV files
csv_files = sorted(glob.glob('sample_outputs/*.csv'))
print(f"Found {len(csv_files)} CSV files")

if not csv_files:
    print("No CSV files found!")
    exit(1)

# Read and aggregate data
data_by_sample = {}

for csv_file in csv_files[:50]:  # Process first 50 files
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
    except Exception as e:
        print(f"  Error loading {filename}: {e}")

print(f"Loaded {len(data_by_sample)} files")

# Now create plots with Plotly
try:
    import plotly.graph_objects as go
    import plotly.subplots as sp
    
    print("Creating plots with Plotly...")
    
    # Plot 1: Overlaid view of all samples
    print("  Creating overlaid plot...")
    fig = go.Figure()
    
    colors = [
        'blue' if 'Mining' in name and 'High' in name else
        'navy' if 'Mining' in name else
        'green' if 'Soil' in name and 'High' in name else
        'darkgreen' if 'Soil' in name else
        'purple' if 'chemistry' in name else
        'red'
        for name in data_by_sample.keys()
    ]
    
    for idx, (filename, (energy, intensity)) in enumerate(data_by_sample.items()):
        sample_type = 'Mining' if 'Mining' in filename else 'Soil' if 'Soil' in filename else 'Chemistry'
        fig.add_trace(go.Scatter(
            x=energy,
            y=intensity,
            mode='lines',
            name=filename[:50],
            line=dict(width=1, color=colors[idx]),
            opacity=0.6,
            hovertemplate=f'<b>{filename}</b><br>Energy: %{{x:.2f}} keV<br>Intensity: %{{y:.2f}} CPS<extra></extra>'
        ))
    
    fig.update_layout(
        title=f'Energy vs Intensity - {len(data_by_sample)} Files (Overlaid)',
        xaxis_title='Energy (keV)',
        yaxis_title='Intensity (CPS)',
        hovermode='x unified',
        template='plotly_white',
        height=600,
        width=1200
    )
    
    fig.write_html('energy_intensity_overlaid.html')
    print("    Saved: energy_intensity_overlaid.html")
    
    # Plot 2: Grid of first 12 samples
    print("  Creating grid plots...") 
    img_files_to_plot = list(data_by_sample.items())[:12]
    
    fig = sp.make_subplots(
        rows=3, cols=4,
        subplot_titles=[f[:25] for f, _ in img_files_to_plot],
        specs=[[{"secondary_y": False}]*4 for _ in range(3)]
    )
    
    row_col_pairs = [(i//4 + 1, i%4 + 1) for i in range(len(img_files_to_plot))]
    
    for (filename, (energy, intensity)), (row, col) in zip(img_files_to_plot, row_col_pairs):
        fig.add_trace(
            go.Scatter(
                x=energy,
                y=intensity,
                mode='lines',
                name=filename[:30],
                line=dict(width=2),
                showlegend=False
            ),
            row=row,
            col=col
        )
    
    fig.update_xaxes(title_text="Energy (keV)", row=3, col=1)
    fig.update_yaxes(title_text="Intensity (CPS)", row=1, col=1)
    fig.update_layout(height=900, width=1400, title_text="Energy vs Intensity - Sample Grid")
    
    fig.write_html('energy_intensity_grid.html')
    print("    Saved: energy_intensity_grid.html")
    
    # Plot 3: Calculate and plot average curve
    print("  Creating average plot...")
    energy_set = set()
    energy_sum = {}
    energy_count = {}
    
    for energy, intensity in data_by_sample.values():
        for e, i in zip(energy, intensity):
            e_rounded = round(e, 2)
            energy_set.add(e_rounded)
            energy_sum[e_rounded] = energy_sum.get(e_rounded, 0) + i
            energy_count[e_rounded] = energy_count.get(e_rounded, 0) + 1
    
    avg_energy = sorted(list(energy_set))
    avg_intensity = [energy_sum[e] / energy_count[e] for e in avg_energy]
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=avg_energy,
        y=avg_intensity,
        mode='lines',
        name='Average',
        line=dict(color='darkblue', width=3),
        fill='tozeroy',
        fillcolor='rgba(0, 0, 139, 0.2)'
    ))
    
    fig.update_layout(
        title=f'Average Energy vs Intensity ({len(data_by_sample)} files)',
        xaxis_title='Energy (keV)',
        yaxis_title='Average Intensity (CPS)',
        template='plotly_white',
        hovermode='x',
        height=600,
        width=1200
    )
    
    fig.write_html('energy_intensity_average.html')
    print("    Saved: energy_intensity_average.html")
    
    print("\nAll plots completed successfully!")
    print("Generated HTML files:")
    print("  - energy_intensity_overlaid.html (interactive, shows all files)")
    print("  - energy_intensity_grid.html (grid view of first 12 files)")
    print("  - energy_intensity_average.html (average curve)")
    
except ImportError as e:
    print(f"Could not import plotly: {e}")
except Exception as e:
    print(f"Error creating plots: {e}")
    import traceback
    traceback.print_exc()

print("\nDone!")
