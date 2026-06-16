import csv
from pathlib import Path

import pandas as pd
import plotly.graph_objs as go
from plotly.subplots import make_subplots

BASE_DIR = Path(__file__).resolve().parent

# Load median element data
median_df = pd.read_csv(BASE_DIR / "median_elem.csv", low_memory=False)
# Load wrong predictions and select first 10
wrong_df = pd.read_csv(BASE_DIR / "wrong_predictions.csv", low_memory=False)
wrong_first10 = wrong_df.head(10)

# Get element base columns (skip metadata and quantile columns)
element_cols = [
    col.replace("_median", "")
    for col in median_df.columns
    if col.endswith("_median") and not col.startswith(("voltage", "test", "target"))
]

# Load element energies lookup table
energy_lookup = {}
with open(BASE_DIR / "element_xray_energies.csv", newline="") as csvfile:
    reader = csv.reader(csvfile)
    for row in reader:
        if not row or row[0].startswith("#") or len(row) < 2:
            continue
        try:
            energy_lookup[row[0]] = float(row[1])
        except ValueError:
            continue


def get_energy(col):
    # Unknown energies go last, then alphabetic.
    return (energy_lookup.get(col, float("inf")), col)


element_cols_sorted = sorted(element_cols, key=get_energy)
unique_targets = median_df["target"].unique()


def to_wrongpred_col(col_name):
    # `median_elem.csv` uses suffixes like Ka/Kb/La/Lb while wrong_predictions.csv
    # stores them as K_alpha/K_beta/L_alpha/L_beta.
    mapping = {
        "_Ka": "_K_alpha",
        "_Kb": "_K_beta",
        "_La": "_L_alpha",
        "_Lb": "_L_beta",
    }
    for src, dst in mapping.items():
        if col_name.endswith(src):
            return col_name[: -len(src)] + dst
    return col_name


wrong_cols_map = {col: to_wrongpred_col(col) for col in element_cols_sorted}
available_elem_cols = [col for col in element_cols_sorted if wrong_cols_map[col] in wrong_df.columns]
missing_elem_cols = [col for col in element_cols_sorted if wrong_cols_map[col] not in wrong_df.columns]

if missing_elem_cols:
    print(
        f"Warning: {len(missing_elem_cols)} element channels not found in wrong_predictions.csv; "
        "overlay lines will use available channels only."
    )

fig = make_subplots(
    rows=len(unique_targets),
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    subplot_titles=[f"Target: {t}" for t in unique_targets],
)

for idx, target in enumerate(unique_targets, 1):
    tdf = median_df[median_df["target"] == target]
    if tdf.empty:
        continue

    med_cols = [f"{col}_median" for col in element_cols_sorted]
    q05_cols = [f"{col}_q05" for col in element_cols_sorted]
    q25_cols = [f"{col}_q25" for col in element_cols_sorted]
    q75_cols = [f"{col}_q75" for col in element_cols_sorted]
    q95_cols = [f"{col}_q95" for col in element_cols_sorted]

    y_q05 = list(tdf.iloc[0][q05_cols])
    y_q25 = list(tdf.iloc[0][q25_cols])
    y_q75 = list(tdf.iloc[0][q75_cols])
    y_q95 = list(tdf.iloc[0][q95_cols])

    # Plot quantile bands first (so they are behind lines), but skip degenerate bands.
    if not (pd.isna(y_q05).all() or pd.isna(y_q95).all() or all(a == b for a, b in zip(y_q05, y_q95))):
        x_band2 = list(element_cols_sorted) + list(element_cols_sorted[::-1])
        y_band2 = y_q05 + y_q95[::-1]
        fig.add_trace(
            go.Scatter(
                x=x_band2,
                y=y_band2,
                fill="toself",
                fillcolor="rgba(0,100,200,0.07)",
                line=dict(width=0),
                showlegend=False,
                name=f"{target} Q05-Q95",
                hoverinfo="skip",
            ),
            row=idx,
            col=1,
        )
    if not (pd.isna(y_q25).all() or pd.isna(y_q75).all() or all(a == b for a, b in zip(y_q25, y_q75))):
        x_band1 = list(element_cols_sorted) + list(element_cols_sorted[::-1])
        y_band1 = y_q25 + y_q75[::-1]
        fig.add_trace(
            go.Scatter(
                x=x_band1,
                y=y_band1,
                fill="toself",
                fillcolor="rgba(0,100,200,0.15)",
                line=dict(width=0),
                showlegend=False,
                name=f"{target} Q25-Q75",
                hoverinfo="skip",
            ),
            row=idx,
            col=1,
        )

    fig.add_trace(
        go.Scatter(
            x=element_cols_sorted,
            y=tdf.iloc[0][med_cols],
            mode="lines",
            name=f"{target} median",
            line=dict(color="blue"),
        ),
        row=idx,
        col=1,
    )

    wrong_target = wrong_first10[wrong_first10["target"] == target]
    if not wrong_target.empty:
        for _, row in wrong_target.iterrows():
            test_val = row["test"]
            fig.add_trace(
                go.Scatter(
                    x=available_elem_cols,
                    y=[row[wrong_cols_map[col]] for col in available_elem_cols],
                    mode="lines",
                    name=f"Wrong: {test_val}",
                    line=dict(color="red", dash="solid", width=1),
                    showlegend=True,
                ),
                row=idx,
                col=1,
            )

fig.update_layout(
    height=400 * len(unique_targets),
    showlegend=True,
    title="Median Element Profile, Quantile Bands, and First 10 Wrong Predictions (Elements, Energy Sorted)",
    xaxis_title="Element (sorted by energy)",
    yaxis_title="Value",
)
fig.show(renderer="browser")
