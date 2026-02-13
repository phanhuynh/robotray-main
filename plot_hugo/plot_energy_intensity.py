"""
Program to plot energy and intensity data from sample_outputs CSV files
"""

import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import glob
from pathlib import Path
import sys

# Define the sample_outputs directory
SAMPLE_OUTPUTS_DIR = "sample_outputs"

def load_csv_files(directory=SAMPLE_OUTPUTS_DIR):
    """Load all CSV files from the specified directory"""
    csv_files = glob.glob(os.path.join(directory, "*.csv"))
    return sorted(csv_files)

def plot_individual_files(csv_files, limit=10):
    """Plot individual CSV files (up to limit)"""
    print(f"Plotting {min(limit, len(csv_files))} individual files...", flush=True)
    
    fig, axes = plt.subplots(nrows=5, ncols=2, figsize=(15, 20))
    axes = axes.flatten()
    
    for idx, csv_file in enumerate(csv_files[:limit]):
        try:
            df = pd.read_csv(csv_file)
            filename = os.path.basename(csv_file)
            
            axes[idx].plot(df['Energy (keV)'], df['Intensity (CPS)'], linewidth=1.5)
            axes[idx].set_xlabel('Energy (keV)')
            axes[idx].set_ylabel('Intensity (CPS)')
            axes[idx].set_title(filename[:40] + '...' if len(filename) > 40 else filename, fontsize=9)
            axes[idx].grid(True, alpha=0.3)
        except Exception as e:
            print(f"Error processing {csv_file}: {e}", flush=True)
            axes[idx].text(0.5, 0.5, f'Error: {str(e)[:30]}', ha='center', va='center')
    
    plt.tight_layout()
    plt.savefig('energy_intensity_individual.png', dpi=150, bbox_inches='tight')
    print("Saved: energy_intensity_individual.png", flush=True)
    plt.close()

def plot_all_overlaid(csv_files):
    """Plot all files overlaid on a single plot"""
    print("Plotting all files overlaid...", flush=True)
    
    plt.figure(figsize=(14, 8))
    
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            plt.plot(df['Energy (keV)'], df['Intensity (CPS)'], alpha=0.3, linewidth=0.8)
        except Exception as e:
            print(f"Error processing {csv_file}: {e}", flush=True)
    
    plt.xlabel('Energy (keV)', fontsize=12)
    plt.ylabel('Intensity (CPS)', fontsize=12)
    plt.title(f'Energy vs Intensity - All {len(csv_files)} Files Overlaid', fontsize=14)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('energy_intensity_overlaid.png', dpi=150, bbox_inches='tight')
    print("Saved: energy_intensity_overlaid.png", flush=True)
    plt.close()

def plot_average(csv_files):
    """Plot the average energy-intensity curve"""
    print("Calculating average curve...", flush=True)
    
    # Load all data
    all_data = []
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            all_data.append(df)
        except Exception as e:
            print(f"Error processing {csv_file}: {e}", flush=True)
    
    if not all_data:
        print("No data loaded!", flush=True)
        return
    
    # Combine all data and calculate mean
    combined_df = pd.concat(all_data, ignore_index=True)
    avg_data = combined_df.groupby('Energy (keV)')['Intensity (CPS)'].mean()
    
    plt.figure(figsize=(14, 8))
    plt.plot(avg_data.index, avg_data.values, linewidth=2.5, color='darkblue')
    plt.xlabel('Energy (keV)', fontsize=12)
    plt.ylabel('Intensity (CPS)', fontsize=12)
    plt.title(f'Average Energy vs Intensity Across {len(csv_files)} Files', fontsize=14)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('energy_intensity_average.png', dpi=150, bbox_inches='tight')
    print("Saved: energy_intensity_average.png", flush=True)
    plt.close()

def plot_by_category(csv_files):
    """Plot grouped by sample type (Mining, Soil, Chemistry)"""
    print("Plotting by category...", flush=True)
    
    categories = {'Mining': [], 'Soil': [], 'Chemistry': []}
    
    for csv_file in csv_files:
        filename = os.path.basename(csv_file)
        if 'Mining' in filename:
            categories['Mining'].append(csv_file)
        elif 'Soil' in filename:
            categories['Soil'].append(csv_file)
        elif 'chemistry' in filename:
            categories['Chemistry'].append(csv_file)
    
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    
    for (cat_name, cat_files), ax in zip(categories.items(), axes):
        for csv_file in cat_files:
            try:
                df = pd.read_csv(csv_file)
                ax.plot(df['Energy (keV)'], df['Intensity (CPS)'], alpha=0.4, linewidth=0.8)
            except Exception as e:
                print(f"Error processing {csv_file}: {e}", flush=True)
        
        ax.set_xlabel('Energy (keV)', fontsize=11)
        ax.set_ylabel('Intensity (CPS)', fontsize=11)
        ax.set_title(f'{cat_name} ({len(cat_files)} files)', fontsize=12)
        ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('energy_intensity_by_category.png', dpi=150, bbox_inches='tight')
    print("Saved: energy_intensity_by_category.png", flush=True)
    plt.close()

def main():
    """Main function"""
    print(f"Looking for CSV files in '{SAMPLE_OUTPUTS_DIR}'...", flush=True)
    
    csv_files = load_csv_files()
    
    if not csv_files:
        print(f"No CSV files found in {SAMPLE_OUTPUTS_DIR}", flush=True)
        return
    
    print(f"Found {len(csv_files)} CSV files", flush=True)
    
    # Create plots
    print("Starting plot generation...", flush=True)
    plot_individual_files(csv_files, limit=10)
    print("Individual files plot complete", flush=True)
    
    plot_all_overlaid(csv_files)
    print("Overlaid plot complete", flush=True)
    
    plot_average(csv_files)
    print("Average plot complete", flush=True)
    
    plot_by_category(csv_files)
    print("Category plots complete", flush=True)
    
    print("\nAll plots completed!", flush=True)
    print("Generated files:", flush=True)
    print("  - energy_intensity_individual.png", flush=True)
    print("  - energy_intensity_overlaid.png", flush=True)
    print("  - energy_intensity_average.png", flush=True)
    print("  - energy_intensity_by_category.png", flush=True)

if __name__ == "__main__":
    main()
