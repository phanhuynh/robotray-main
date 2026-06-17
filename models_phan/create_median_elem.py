import pandas as pd
from pathlib import Path
import warnings

input_path = Path(r"C:/Users/phuynh/Projects/robotray-main/models_phan/df_snr_elem.csv")
output_path = Path(r"C:/Users/phuynh/Projects/robotray-main/models_phan/median_elem.csv")

warnings.filterwarnings("ignore", category=FutureWarning)

if not input_path.exists():
    raise FileNotFoundError(f"df_snr_elem.csv not found at: {input_path}")

all_snr = pd.read_csv(input_path)

meta_cols = ["target", "voltage"]
raw_meta_cols = ["test", "target", "voltage"]
energy_cols = [c for c in all_snr.columns if c not in raw_meta_cols]
if not energy_cols:
    raise ValueError("No energy columns found. Check df_snr_elem.csv headers.")

all_snr["target"] = all_snr["target"].astype(str).str.strip()
all_snr["voltage"] = all_snr["voltage"].astype(str).str.strip()

# IMPORTANT: ensure numeric
all_snr[energy_cols] = all_snr[energy_cols].apply(pd.to_numeric, errors="coerce")

grouped = all_snr.groupby(meta_cols)[energy_cols]

median = grouped.median().reset_index().rename(columns={c: f"{c}_median" for c in energy_cols})
q05 = grouped.quantile(0.05).reset_index().rename(columns={c: f"{c}_q05" for c in energy_cols})
q25 = grouped.quantile(0.25).reset_index().rename(columns={c: f"{c}_q25" for c in energy_cols})
q75 = grouped.quantile(0.75).reset_index().rename(columns={c: f"{c}_q75" for c in energy_cols})
q95 = grouped.quantile(0.95).reset_index().rename(columns={c: f"{c}_q95" for c in energy_cols})

merged = median.merge(q05, on=meta_cols).merge(q25, on=meta_cols).merge(q75, on=meta_cols).merge(q95, on=meta_cols)
merged.to_csv(output_path, index=False)

print(f"Saved: {output_path}  (rows={len(merged)})")
print("Example zircon rows:", len(merged[merged["target"]=="zircon"]))