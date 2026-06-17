# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.1
#   kernelspec:
#     display_name: 550_model
#     language: python
#     name: python3
# ---

# %% [markdown]
# # PyCaret SNR Classification Workflow
#
# **Instructions Summary:**
#
#
# - Use the SNR dataset at `plots_phan/cached_spectrums/snr_all.csv` as the main data source.
# - Build a PyCaret-based classification workflow, including:
#   - Loading and exploring the dataset.
#   - Preprocessing (handle missing values, encode categoricals, scale numerics).
#   - Feature engineering as needed.
#   - Model selection, training, and evaluation using PyCaret.
#   - Hyperparameter tuning and model persistence.
# - Ensure the workflow is reproducible and modular, with clear steps for each stage.
# - Use the `550_model` environment (Python 3.9 with PyCaret installed) for compatibility.
#

# %%
# 1. Load SNR Dataset
import pandas as pd
df_snr = pd.read_csv(r'C:/Users/phuynh/Projects/robotray-main/plots_phan/cached_spectrums/snr_all.csv')
print(f"Loaded SNR dataset with shape: {df_snr.shape}")
df_snr.head()

# %%
# 2. Extract supervised solution (target) from session column
# The target is the mineral section, e.g., 'nephe1s' from '002854_2026_02_09_nephe1s_150'
import re

def extract_target(session):
    # Extract the section between the last two underscores
    match = re.match(r"\d+_\d{4}_\d{2}_\d{2}_(.*?)_\d+$", session)
    if match:
        return match.group(1)
    return None

df_snr['target'] = df_snr['session'].astype(str).apply(extract_target)
print(df_snr[['session', 'target']].head())

# %%
#shape of df_snr
print(f"Shape of df_snr: {df_snr.shape}")
#show head of df_snr
df_snr.head()

# %%
# Show example of duplicate rows for (session, voltage, target, Energy (keV))
dupes = df_snr.duplicated(subset=['session', 'voltage', 'Energy (keV)'], keep=False)
df_duplicates = df_snr[dupes].sort_values(['session', 'voltage', 'Energy (keV)'])
print(f"Number of duplicate rows: {df_duplicates.shape[0]}")
df_duplicates.head(10)

# %%
# 3. Export processed DataFrame for reuse
df_snr.to_csv(r'C:\Users\phuynh\Projects\robotray-main\models_phan\df_snr.csv', index=False)
try:
    df_snr.to_parquet(r'C:\Users\phuynh\Projects\robotray-main\models_phan\df_snr.parquet', index=False)
    print('Exported to both CSV and Parquet.')
except ImportError:
    print('pyarrow or fastparquet not installed; only CSV export completed.')

# %%
# 6. Extract and reduce to main energy lines (K/L alpha/beta) with element labels, up to 40 keV
# Expanded list of K/L alpha/beta energy lines (in keV) with element labels
energy_lines = [
    # Format: (element, line_type, energy_keV)
    # K lines (light to heavy)
    ('Mg', 'K_alpha', 1.2536), ('Mg', 'K_beta', 1.302),
    ('Al', 'K_alpha', 1.4867), ('Al', 'K_beta', 1.550),
    ('Si', 'K_alpha', 1.740), ('Si', 'K_beta', 1.836),
    ('P', 'K_alpha', 2.0137), ('P', 'K_beta', 2.139),
    ('S', 'K_alpha', 2.307), ('S', 'K_beta', 2.464),
    ('Cl', 'K_alpha', 2.622), ('Cl', 'K_beta', 2.815),
    ('K', 'K_alpha', 3.312), ('K', 'K_beta', 3.590),
    ('Ca', 'K_alpha', 3.691), ('Ca', 'K_beta', 4.012),
    ('Ti', 'K_alpha', 4.5108), ('Ti', 'K_beta', 4.9318),
    ('V', 'K_alpha', 4.952), ('V', 'K_beta', 5.427),
    ('Cr', 'K_alpha', 5.415), ('Cr', 'K_beta', 5.946),
    ('Mn', 'K_alpha', 5.8988), ('Mn', 'K_beta', 6.490),
    ('Fe', 'K_alpha', 6.4038), ('Fe', 'K_beta', 7.058),
    ('Co', 'K_alpha', 6.930), ('Co', 'K_beta', 7.649),
    ('Ni', 'K_alpha', 7.478), ('Ni', 'K_beta', 8.265),
    ('Cu', 'K_alpha', 8.048), ('Cu', 'K_beta', 8.905),
    ('Zn', 'K_alpha', 8.6389), ('Zn', 'K_beta', 9.572),
    ('Ga', 'K_alpha', 9.251), ('Ga', 'K_beta', 10.264),
    ('Ge', 'K_alpha', 9.886), ('Ge', 'K_beta', 10.982),
    ('As', 'K_alpha', 10.543), ('As', 'K_beta', 11.723),
    ('Se', 'K_alpha', 11.222), ('Se', 'K_beta', 12.486),
    ('Br', 'K_alpha', 11.924), ('Br', 'K_beta', 13.272),
    ('Rb', 'K_alpha', 13.395), ('Rb', 'K_beta', 14.829),
    ('Sr', 'K_alpha', 14.165), ('Sr', 'K_beta', 15.682),
    ('Y', 'K_alpha', 14.958), ('Y', 'K_beta', 16.738),
    ('Zr', 'K_alpha', 15.775), ('Zr', 'K_beta', 17.667),
    ('Nb', 'K_alpha', 16.615), ('Nb', 'K_beta', 18.629),
    ('Mo', 'K_alpha', 17.479), ('Mo', 'K_beta', 19.608),
    ('Ru', 'K_alpha', 19.278), ('Ru', 'K_beta', 21.654),
    ('Rh', 'K_alpha', 20.216), ('Rh', 'K_beta', 22.747),
    ('Pd', 'K_alpha', 21.174), ('Pd', 'K_beta', 23.864),
    ('Ag', 'K_alpha', 22.163), ('Ag', 'K_beta', 25.013),
    ('Cd', 'K_alpha', 23.173), ('Cd', 'K_beta', 26.187),
    ('In', 'K_alpha', 24.208), ('In', 'K_beta', 27.389),
    ('Sn', 'K_alpha', 25.271), ('Sn', 'K_beta', 28.619),
    ('Sb', 'K_alpha', 26.359), ('Sb', 'K_beta', 29.877),
    ('Te', 'K_alpha', 27.472), ('Te', 'K_beta', 31.164),
    ('I', 'K_alpha', 28.612), ('I', 'K_beta', 32.480),
    ('Ba', 'K_alpha', 29.779), ('Ba', 'K_beta', 33.825),
    ('La', 'K_alpha', 30.974), ('La', 'K_beta', 35.200),
    ('Ce', 'K_alpha', 32.197), ('Ce', 'K_beta', 36.604),
    ('Pr', 'K_alpha', 33.448), ('Pr', 'K_beta', 38.038),
    ('Nd', 'K_alpha', 34.728), ('Nd', 'K_beta', 39.502),
    # L lines (heavier elements)
    ('Zr', 'L_alpha', 2.042), ('Zr', 'L_beta', 2.307),
    ('Mo', 'L_alpha', 2.293), ('Mo', 'L_beta', 2.629),
    ('Ag', 'L_alpha', 2.984), ('Ag', 'L_beta', 3.150),
    ('Sn', 'L_alpha', 3.443), ('Sn', 'L_beta', 3.670),
    ('Ba', 'L_alpha', 4.465), ('Ba', 'L_beta', 4.830),
    ('La', 'L_alpha', 4.650), ('La', 'L_beta', 5.030),
    ('Ce', 'L_alpha', 4.839), ('Ce', 'L_beta', 5.236),
    ('Pb', 'L_alpha', 10.551), ('Pb', 'L_beta', 12.614),
    # Add more as needed up to 40 keV
]


# %%

# %%
# 5. Apply PyCaret to each voltage and output confidence for all targets
from pycaret.classification import setup, compare_models, predict_model

# Identify unique voltages
voltages = df_snr['voltage'].unique()
results = {}

for voltage in voltages:
    print(f"Processing voltage: {voltage}")
    df_voltage = df_snr[df_snr['voltage'] == voltage].copy()
    clf_setup = setup(data=df_voltage, target='target', session_id=42, verbose=False)
    best_model = compare_models()
    preds = predict_model(best_model, data=df_voltage)
    # Extract confidence for each possible target
    confidence_cols = [col for col in preds.columns if col not in ['Label', 'Score', 'target']]
    confidence_df = preds[confidence_cols]
    results[voltage] = confidence_df
    print(confidence_df.head())

# Example: access confidence for a voltage
# results['150']

# %%
# 7. Create df_element.csv: metadata + SNR at labeled energy lines only
import pandas as pd
import numpy as np
from scipy.interpolate import interp1d

# Load df_snr.csv (wide format: metadata + energy columns)
df_snr = pd.read_csv(r'C:/Users/phuynh/Projects/robotray-main/models_phan/df_snr.csv')

# Define energy lines and labels (same as before)
energy_lines = [
    ('Mg', 'K_alpha', 1.2536), ('Mg', 'K_beta', 1.302),
    ('Al', 'K_alpha', 1.4867), ('Al', 'K_beta', 1.550),
    ('Si', 'K_alpha', 1.740), ('Si', 'K_beta', 1.836),
    ('P', 'K_alpha', 2.0137), ('P', 'K_beta', 2.139),
    ('S', 'K_alpha', 2.307), ('S', 'K_beta', 2.464),
    ('Cl', 'K_alpha', 2.622), ('Cl', 'K_beta', 2.815),
    ('K', 'K_alpha', 3.312), ('K', 'K_beta', 3.590),
    ('Ca', 'K_alpha', 3.691), ('Ca', 'K_beta', 4.012),
    ('Ti', 'K_alpha', 4.5108), ('Ti', 'K_beta', 4.9318),
    ('V', 'K_alpha', 4.952), ('V', 'K_beta', 5.427),
    ('Cr', 'K_alpha', 5.415), ('Cr', 'K_beta', 5.946),
    ('Mn', 'K_alpha', 5.8988), ('Mn', 'K_beta', 6.490),
    ('Fe', 'K_alpha', 6.4038), ('Fe', 'K_beta', 7.058),
    ('Co', 'K_alpha', 6.930), ('Co', 'K_beta', 7.649),
    ('Ni', 'K_alpha', 7.478), ('Ni', 'K_beta', 8.265),
    ('Cu', 'K_alpha', 8.048), ('Cu', 'K_beta', 8.905),
    ('Zn', 'K_alpha', 8.6389), ('Zn', 'K_beta', 9.572),
    ('Ga', 'K_alpha', 9.251), ('Ga', 'K_beta', 10.264),
    ('Ge', 'K_alpha', 9.886), ('Ge', 'K_beta', 10.982),
    ('As', 'K_alpha', 10.543), ('As', 'K_beta', 11.723),
    ('Se', 'K_alpha', 11.222), ('Se', 'K_beta', 12.486),
    ('Br', 'K_alpha', 11.924), ('Br', 'K_beta', 13.272),
    ('Rb', 'K_alpha', 13.395), ('Rb', 'K_beta', 14.829),
    ('Sr', 'K_alpha', 14.165), ('Sr', 'K_beta', 15.682),
    ('Y', 'K_alpha', 14.958), ('Y', 'K_beta', 16.738),
    ('Zr', 'K_alpha', 15.775), ('Zr', 'K_beta', 17.667),
    ('Nb', 'K_alpha', 16.615), ('Nb', 'K_beta', 18.629),
    ('Mo', 'K_alpha', 17.479), ('Mo', 'K_beta', 19.608),
    ('Ru', 'K_alpha', 19.278), ('Ru', 'K_beta', 21.654),
    ('Rh', 'K_alpha', 20.216), ('Rh', 'K_beta', 22.747),
    ('Pd', 'K_alpha', 21.174), ('Pd', 'K_beta', 23.864),
    ('Ag', 'K_alpha', 22.163), ('Ag', 'K_beta', 25.013),
    ('Cd', 'K_alpha', 23.173), ('Cd', 'K_beta', 26.187),
    ('In', 'K_alpha', 24.208), ('In', 'K_beta', 27.389),
    ('Sn', 'K_alpha', 25.271), ('Sn', 'K_beta', 28.619),
    ('Sb', 'K_alpha', 26.359), ('Sb', 'K_beta', 29.877),
    ('Te', 'K_alpha', 27.472), ('Te', 'K_beta', 31.164),
    ('I', 'K_alpha', 28.612), ('I', 'K_beta', 32.480),
    ('Ba', 'K_alpha', 29.779), ('Ba', 'K_beta', 33.825),
    ('La', 'K_alpha', 30.974), ('La', 'K_beta', 35.200),
    ('Ce', 'K_alpha', 32.197), ('Ce', 'K_beta', 36.604),
    ('Pr', 'K_alpha', 33.448), ('Pr', 'K_beta', 38.038),
    ('Nd', 'K_alpha', 34.728), ('Nd', 'K_beta', 39.502),
    # L lines (heavier elements)
    ('Zr', 'L_alpha', 2.042), ('Zr', 'L_beta', 2.307),
    ('Mo', 'L_alpha', 2.293), ('Mo', 'L_beta', 2.629),
    ('Ag', 'L_alpha', 2.984), ('Ag', 'L_beta', 3.150),
    ('Sn', 'L_alpha', 3.443), ('Sn', 'L_beta', 3.670),
    ('Ba', 'L_alpha', 4.465), ('Ba', 'L_beta', 4.830),
    ('La', 'L_alpha', 4.650), ('La', 'L_beta', 5.030),
    ('Ce', 'L_alpha', 4.839), ('Ce', 'L_beta', 5.236),
    ('Pb', 'L_alpha', 10.551), ('Pb', 'L_beta', 12.614),
]
labeled_lines = [(f"{el}_{lt}", energy) for el, lt, energy in energy_lines]

# Identify metadata columns (all non-numeric columns except energy columns)
metadata_cols = [col for col in df_snr.columns if not any(char.isdigit() for char in col)]
energy_cols = [col for col in df_snr.columns if col not in metadata_cols]

# Prepare output DataFrame
rows = []
for idx, row in df_snr.iterrows():
    # Get energy and SNR values for this row
    energies = np.array([float(col) / 1000 for col in energy_cols])  # convert eV to keV
    values = row[energy_cols].values.astype(float)
    f = interp1d(energies, values, bounds_error=False, fill_value='extrapolate')
    snr_at_lines = f([energy for _, energy in labeled_lines])
    row_dict = {col: row[col] for col in metadata_cols}
    for (label, _), val in zip(labeled_lines, snr_at_lines):
        row_dict[label] = val
    rows.append(row_dict)

# Create DataFrame and export
df_element = pd.DataFrame(rows)
df_element.to_csv(r'C:/Users/phuynh/Projects/robotray-main/models_phan/df_element.csv', index=False)
try:
    df_element.to_parquet(r'C:/Users/phuynh/Projects/robotray-main/models_phan/df_element.parquet', index=False)
    print('Exported df_element to both CSV and Parquet.')
except ImportError:
    print('pyarrow or fastparquet not installed; only CSV export completed.')
