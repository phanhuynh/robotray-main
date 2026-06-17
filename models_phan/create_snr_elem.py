import pandas as pd
import re
from energy_lines_ref import get_energy_lines

df_snr = pd.read_csv(r'C:/Users/phuynh/Projects/robotray-main/plots_phan/cached_spectrums/snr_all.csv')

print(f"Loaded SNR dataset with shape: {df_snr.shape}")
df_snr.head()

# Shared energy-line reference (short notation keeps current output labels).
energy_lines = get_energy_lines(notation="short", max_kev=30.0, sort_by_energy=True)

print(f"Number of energy lines: {len(energy_lines)}")


### REDUCE DF TO ELEMENTS AND TRANSPOSE:  df_snr_elem

import numpy as np

energy_labels = [f"{el}_{lt}" for el, lt, _ in energy_lines]
energy_values = [energy for _, _, energy in energy_lines]

# 4. For each group, keep only SNR values nearest to each energy line
def nearest_snr_to_lines(group):
    voltage, test, target = group.name
    result = {
        'voltage': voltage,
        'test': test,
        'target': target
    }
    energies = group['Energy (keV)'].values
    snrs = group['SNR'].values
    for label, target_energy in zip(energy_labels, energy_values):
        idx = (np.abs(energies - target_energy)).argmin()
        result[label] = snrs[idx]
    return pd.Series(result)

df_snr_elem = (
    df_snr.groupby(['voltage', 'test', 'target'])
    .apply(nearest_snr_to_lines)
    .reset_index(drop=True)
)

print(df_snr_elem.head())

# 3. Export processed DataFrame for reuse
df_snr_elem.to_csv(r'C:\Users\phuynh\Projects\robotray-main\models_phan\df_snr_elem.csv', index=False)
try:
    df_snr_elem.to_parquet(r'C:\Users\phuynh\Projects\robotray-main\models_phan\df_snr_elem.parquet', index=False)
    print('Exported to both CSV and Parquet.')
except ImportError:
    print('pyarrow or fastparquet not installed; only CSV export completed.')