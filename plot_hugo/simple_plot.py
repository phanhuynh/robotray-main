#!/usr/bin/env python3
"""
Simple program to plot energy and intensity data
"""
import os
import glob
import csv

# Find CSV files
csv_files = sorted(glob.glob('sample_outputs/*.csv'))
print(f"Found {len(csv_files)} CSV files")

if not csv_files:
    print("No CSV files found!")
    exit(1)

# Read and aggregate data
all_energy = []
all_intensity = []
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
            all_energy.append(energy)
            all_intensity.append(intensity)
            data_by_sample[filename] = (energy, intensity)
            print(f"  Loaded {filename}: {len(energy)} points")
    except Exception as e:
        print(f"  Error loading {filename}: {e}")

print(f"\nSuccessfully loaded {len(data_by_sample)} files")
print(f"Total data points across all files: {sum(len(e) for e in all_energy)}")

# Now try plotting with matplotlib
try:
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
    import matplotlib.pyplot as plt
    print("\nMatplotlib initialized")
    
    # Create a plot
    plt.figure(figsize=(14, 8))
    
    for energy, intensity in list(zip(all_energy, all_intensity))[:10]:
        plt.plot(energy, intensity, alpha=0.5, linewidth=1)
    
    plt.xlabel('Energy (keV)', fontsize=12)
    plt.ylabel('Intensity (CPS)', fontsize=12)
    plt.title(f'Energy vs Intensity - {len(data_by_sample)} Files', fontsize=14)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('energy_intensity_plot.png', dpi=150, bbox_inches='tight')
    print("Plot saved: energy_intensity_plot.png")
    plt.close()
    
except ImportError as e:
    print(f"Could not import matplotlib: {e}")
except Exception as e:
    print(f"Error creating plot: {e}")
    import traceback
    traceback.print_exc()

print("\nDone!")
