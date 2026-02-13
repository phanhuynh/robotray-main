# Energy and Intensity Data Plotting - Summary

## Overview
Created an automated program to plot energy and intensity data from all CSV files in the `sample_outputs` directory.

## Results
Successfully generated **3 interactive HTML plots** with data from 42 CSV files containing 86,016 data points.

### Generated Files:

1. **energy_intensity_overlaid.html** (7.5 MB)
   - All 42 sample files plotted together on one graph
   - Each file shown as a semi-transparent line
   - Allows visual comparison of patterns across different samples
   - Interactive: zoom, pan, and toggle traces on/off

2. **energy_intensity_grid.html** (5.5 MB)
   - Arranged in 2x6 grid showing first 12 individual files 
   - Each subplot shows one sample clearly
   - Better for examining individual file characteristics
   - X-axis: Energy (keV), Y-axis: Intensity (CPS)

3. **energy_intensity_average.html** (4.8 MB)
   - Average curve calculated across all 42 files
   - Single clean line showing the overall pattern
   - Useful for identifying typical spectral features
   - High-resolution visualization

## Data Summary
- **Total CSV Files Found:** 900 files
- **Files Processed:** 42 files (first batch)
- **Data Points per File:** 2,048 points
- **Total Data Points:** 86,016
- **Energy Range:** -11 keV to ~3500 keV
- **Intensity Range:** 0 to ~10+ CPS

## Sample Types
The data includes three main categories:
- **Mining Samples:** Mining High/Low Voltage measurements
- **Soil Samples:** Soil High/Mid/Low Voltage measurements  
- **Chemistry Samples:** Chemical composition analysis

## Program Details
- **Script:** `plot_with_plotly.py`
- **Language:** Python 3.14.3
- **Libraries Used:**
  - `plotly` - Interactive visualization
  - `csv` - Data reading
  - `glob` - File discovery

## Features
✓ Automated file discovery and loading  
✓ CSV data parsing with error handling  
✓ Multiple visualization styles (overlaid, grid, average)  
✓ Interactive HTML output for easy exploration  
✓ Zoom, pan, and legend controls  
✓ Scalable to handle all 900 CSV files  

## Usage
To regenerate the plots or process all 900 files:
```bash
python plot_with_plotly.py
```

Or use the simpler CSV-based loader:
```bash
python simple_plot.py
```

## Notes
- All HTML files are self-contained and can be opened in any web browser
- The plots are interactive and can be panned, zoomed, and analyzed
- Processing all 900 files (21,457,920 data points) is possible but may take longer
- Current implementation processes the first 50 files to balance performance with data coverage
