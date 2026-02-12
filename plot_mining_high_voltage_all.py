"""
Plot energy and intensity from all MiningHighVoltage CSV files in sample_outputs
"""
import pandas as pd
import matplotlib.pyplot as plt
import os
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
file_names = []

for file_path in files:
    try:
        df = pd.read_csv(file_path)
        all_data.append(df)
        file_names.append(file_path.stem)
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

# Create the plot
fig, ax = plt.subplots(figsize=(12, 6))

# Plot as scatter with some transparency
ax.scatter(combined_df['Energy (keV)'], combined_df['Intensity (CPS)'], 
           alpha=0.3, s=10, color='blue')

# Add labels and title
ax.set_xlabel('Energy (keV)', fontsize=12)
ax.set_ylabel('Intensity (CPS)', fontsize=12)
ax.set_title(f'Mining High Voltage: Energy vs Intensity\n({len(files)} files, {len(combined_df)} data points)', 
             fontsize=14, fontweight='bold')

# Add grid
ax.grid(True, alpha=0.3)

# Add a line plot for better visibility
ax.plot(combined_df['Energy (keV)'], combined_df['Intensity (CPS)'], 
        color='blue', alpha=0.1, linewidth=0.5)

plt.tight_layout()

# Save the plot
output_file = "mining_high_voltage_combined_plot.html"
fig.savefig("mining_high_voltage_combined_plot.png", dpi=150, bbox_inches='tight')
print(f"\nPlot saved as: mining_high_voltage_combined_plot.png")

plt.show()
