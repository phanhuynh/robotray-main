"""
Interactive Plotly plot of energy and intensity from all MiningHighVoltage CSV files
"""
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path

# Define the path to sample_outputs
sample_outputs_dir = Path("sample_outputs")

# Find all MiningHighVoltage files (case-insensitive)
files = sorted([
    f for f in sample_outputs_dir.glob("*MiningHighVoltage*.csv")
])

print(f"Found {len(files)} MiningHighVoltage files")

if not files:
    print("No MiningHighVoltage files found in sample_outputs!")
    exit()

# Read and combine all data
all_data = []

for file_path in files:
    try:
        df = pd.read_csv(file_path)
        df['File'] = file_path.stem
        all_data.append(df)
        print(f"Loaded: {file_path.name}")
    except Exception as e:
        print(f"Error loading {file_path.name}: {e}")

if not all_data:
    print("Could not load any files!")
    exit()

# Combine all dataframes
combined_df = pd.concat(all_data, ignore_index=True)

print(f"\nTotal data points: {len(combined_df)}")
print(f"Energy range: {combined_df['Energy (keV)'].min():.2f} to {combined_df['Energy (keV)'].max():.2f} keV")
print(f"Intensity range: {combined_df['Intensity (CPS)'].min():.2f} to {combined_df['Intensity (CPS)'].max():.2f} CPS")

# Create interactive Plotly figure
fig = go.Figure()

# Add scatter plot for all data
fig.add_trace(go.Scatter(
    x=combined_df['Energy (keV)'],
    y=combined_df['Intensity (CPS)'],
    mode='markers',
    marker=dict(
        size=4,
        color='rgba(0, 100, 200, 0.4)',
        line=dict(width=0)
    ),
    name='Data Points',
    hovertemplate='<b>Energy:</b> %{x:.2f} keV<br><b>Intensity:</b> %{y:.2f} CPS<extra></extra>'
))

# Add a line trace for smoothed visualization
combined_df_sorted = combined_df.sort_values('Energy (keV)')
fig.add_trace(go.Scatter(
    x=combined_df_sorted['Energy (keV)'],
    y=combined_df_sorted['Intensity (CPS)'],
    mode='lines',
    name='Data Trend',
    line=dict(color='rgba(0, 100, 200, 0.2)', width=1),
    hoverinfo='skip'
))

# Update layout
fig.update_layout(
    title=f'Mining High Voltage: Energy vs Intensity<br><sub>{len(files)} files, {len(combined_df)} data points</sub>',
    xaxis_title='Energy (keV)',
    yaxis_title='Intensity (CPS)',
    hovermode='closest',
    template='plotly_white',
    height=600,
    width=1200,
    font=dict(size=12)
)

# Save to HTML
output_file = "mining_high_voltage_combined_interactive.html"
fig.write_html(output_file)
print(f"\nInteractive plot saved as: {output_file}")

# Also get some statistics
print("\n" + "="*50)
print("STATISTICS")
print("="*50)
print(f"Mean Energy: {combined_df['Energy (keV)'].mean():.2f} keV")
print(f"Mean Intensity: {combined_df['Intensity (CPS)'].mean():.2f} CPS")
print(f"Max Intensity: {combined_df['Intensity (CPS)'].max():.2f} CPS at Energy {combined_df.loc[combined_df['Intensity (CPS)'].idxmax(), 'Energy (keV)']:.2f} keV")
print(f"Non-zero intensity points: {(combined_df['Intensity (CPS)'] > 0).sum()}")
