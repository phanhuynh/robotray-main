import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from energy_lines_ref import get_energy_lines

WRONG_PATH = "models_phan/wrong_predictions.csv"
STATS_PATH = "models_phan/median_elem.csv"
TOP_N_PER_BUCKET = 2
DEFAULT_VOLTAGE = "mining_high_voltage"
PLOT_EXPERIMENT = "per_voltage"
EXCLUDED_SOURCE_GROUPS = {"mininghighvoltage"}
HTML_OUTPUT_PATH = "models_phan/wrong_predictions_plot.html"
BASE_DIR = Path(__file__).resolve().parent

energy_lines = get_energy_lines(notation="canonical", sort_by_energy=False)
energy_map = {f"{el}_{lt}": float(e) for el, lt, e in energy_lines}

TARGET_LINE_COLOR = "#0072B2"
TARGET_IQR_COLOR = "rgba(0,114,178,0.25)"
TARGET_WIDE_COLOR = "rgba(0,114,178,0.12)"
PRED_LINE_COLOR = "#D62728"
PRED_IQR_COLOR = "rgba(214,39,40,0.25)"
PRED_WIDE_COLOR = "rgba(214,39,40,0.12)"
SAMPLE_LINE_COLOR = "black"


def norm_str(x):
    return str(x).strip()


def norm_voltage(v):
    return str(v).strip().lower().replace("_", "").replace(" ", "")


def fmt_pct(v):
    try:
        return f"{float(v):.1f}%"
    except Exception:
        return "NA"


def line_abbrev(line_type: str) -> str:
    return {"K_alpha": "Ka", "K_beta": "Kb", "L_alpha": "La", "L_beta": "Lb"}.get(line_type, line_type)


def short_feature_key(base_key: str) -> str:
    """Convert canonical key (Mg_K_alpha) to short key (Mg_Ka)."""
    parts = base_key.split("_")
    if len(parts) != 3:
        return base_key
    return f"{parts[0]}_{line_abbrev(parts[1] + '_' + parts[2])}"


def canonical_feature_key(col: str) -> Optional[str]:
    match = re.match(r"^([A-Za-z]+)_(Ka|Kb|La|Lb|K_alpha|K_beta|L_alpha|L_beta)(?:_|$)", str(col))
    if not match:
        return None
    line = match.group(2)
    line_map = {"Ka": "K_alpha", "Kb": "K_beta", "La": "L_alpha", "Lb": "L_beta"}
    return f"{match.group(1)}_{line_map.get(line, line)}"


def tick_label(base_key: str) -> str:
    parts = base_key.split("_")
    if len(parts) != 3:
        return base_key
    e = energy_map.get(base_key, np.nan)
    if np.isnan(e):
        return base_key
    return f"{parts[0]}_{line_abbrev(parts[1] + '_' + parts[2])}_{e:.2f}"


def get_class_row(stats_df: pd.DataFrame, label: str, voltage_norm: str):
    label = norm_str(label)
    r = stats_df[(stats_df["target"] == label) & (stats_df["voltage"] == voltage_norm)]
    if not r.empty:
        return r.iloc[0]
    r = stats_df[stats_df["target"] == label]
    return None if r.empty else r.iloc[0]


def get_stats_arr(row: pd.Series, suffix: str, base_keys: list[str], stats_df: pd.DataFrame):
    # Stats files may use canonical keys (Mg_K_alpha_*) or short keys (Mg_Ka_*).
    cols_canonical = [f"{k}_{suffix}" for k in base_keys]
    if all(c in stats_df.columns for c in cols_canonical):
        return row[cols_canonical].to_numpy(dtype=float)

    cols_short = [f"{short_feature_key(k)}_{suffix}" for k in base_keys]
    if all(c in stats_df.columns for c in cols_short):
        return row[cols_short].to_numpy(dtype=float)

    return None


def add_band(fig, row_i, x, low, high, fillcolor, name, showlegend):
    fig.add_trace(
        go.Scatter(
            x=np.concatenate([x, x[::-1]]),
            y=np.concatenate([low, high[::-1]]),
            fill="toself",
            fillcolor=fillcolor,
            line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="skip",
            name=name,
            showlegend=showlegend,
        ),
        row=row_i,
        col=1,
    )


def extract_feature_payload(row: pd.Series):
    cols = []
    for c in row.index:
        if str(c).startswith(("prediction_score_", "Confidence_")):
            continue
        if pd.isna(row[c]):
            continue
        base_key = canonical_feature_key(str(c))
        if base_key is None:
            continue
        cols.append((str(c), base_key))

    cols = sorted(cols, key=lambda t: (energy_map.get(t[1], np.inf), t[0]))
    if not cols:
        return None

    feature_cols = [c for c, _ in cols]
    base_keys = [k for _, k in cols]
    x = np.arange(len(feature_cols))
    y_sample = row[feature_cols].astype(float).to_numpy()
    x_labels = [tick_label(k) for _, k in cols]
    return x, y_sample, x_labels, base_keys


wrong_pred = pd.read_csv(BASE_DIR / Path(WRONG_PATH).name, low_memory=False).copy()
if "target" not in wrong_pred.columns or "prediction_label" not in wrong_pred.columns:
    raise ValueError("Combined wrong file must include 'target' and 'prediction_label'.")

if "experiment" not in wrong_pred.columns:
    wrong_pred["experiment"] = "unknown_experiment"
if "source_group" not in wrong_pred.columns:
    wrong_pred["source_group"] = ""

wrong_pred["target"] = wrong_pred["target"].map(norm_str)
wrong_pred["prediction_label"] = wrong_pred["prediction_label"].map(norm_str)
wrong_pred["experiment"] = wrong_pred["experiment"].astype(str)
wrong_pred["source_group"] = wrong_pred["source_group"].fillna("").astype(str)
if "voltage" in wrong_pred.columns:
    wrong_pred["voltage"] = wrong_pred["voltage"].astype(str)

if "wrong_margin" in wrong_pred.columns:
    wrong_pred["wrong_margin"] = pd.to_numeric(wrong_pred["wrong_margin"], errors="coerce")
    wrong_pred = wrong_pred.sort_values("wrong_margin", ascending=False)

if PLOT_EXPERIMENT:
    wrong_pred = wrong_pred[wrong_pred["experiment"] == PLOT_EXPERIMENT].copy()
if EXCLUDED_SOURCE_GROUPS:
    wrong_pred = wrong_pred[~wrong_pred["source_group"].isin(EXCLUDED_SOURCE_GROUPS)].copy()

bucket_cols = ["experiment", "source_group"]
selected = (
    wrong_pred.groupby(bucket_cols, dropna=False, as_index=False, group_keys=False)
    .head(TOP_N_PER_BUCKET)
    .reset_index(drop=True)
)

plot_rows = []
titles = []
for _, row in selected.iterrows():
    payload = extract_feature_payload(row)
    if payload is None:
        continue
    plot_rows.append((row, payload))
    margin_txt = f" | wrong_margin={fmt_pct(row.get('wrong_margin'))}" if "wrong_margin" in row else ""
    src = f" | source_group={row['source_group']}" if row.get("source_group", "") else ""
    volt = f" | voltage={row.get('voltage', DEFAULT_VOLTAGE)}"
    titles.append(
        f"{row['experiment']}{src}{volt} | target={row['target']} | pred={row['prediction_label']}{margin_txt}"
    )

if not plot_rows:
    raise ValueError("No plottable rows found. Check wrong_predictions.csv feature columns.")

stats = None
med_suffix = None
has_quantiles = False
stats_path = BASE_DIR / Path(STATS_PATH).name
if stats_path.exists():
    stats = pd.read_csv(stats_path).copy()
    if {"target", "voltage"}.issubset(stats.columns):
        stats["target"] = stats["target"].map(norm_str)
        stats["voltage"] = stats["voltage"].map(norm_voltage)
        possible_suffixes = ["q05", "q25", "median", "q75", "q95", "med"]
        present_suffixes = [s for s in possible_suffixes if any(col.endswith(f"_{s}") for col in stats.columns)]
        if present_suffixes:
            med_suffix = "median" if "median" in present_suffixes else ("med" if "med" in present_suffixes else present_suffixes[0])
            has_quantiles = all(any(col.endswith(f"_{s}") for col in stats.columns) for s in ["q05", "q25", "q75", "q95"])
    else:
        stats = None

fig = make_subplots(
    rows=len(plot_rows),
    cols=1,
    shared_xaxes=False,
    vertical_spacing=0.05,
    subplot_titles=titles,
)

for i, (row, payload) in enumerate(plot_rows, start=1):
    x, y_sample, x_labels, base_keys = payload
    target = row["target"]
    pred = row["prediction_label"]

    fig.add_trace(
        go.Scatter(
            x=x,
            y=y_sample,
            mode="lines",
            line=dict(color=SAMPLE_LINE_COLOR, width=2),
            name="Sample (wrong prediction)",
            showlegend=(i == 1),
        ),
        row=i,
        col=1,
    )

    if stats is not None and med_suffix is not None:
        row_voltage = norm_voltage(row.get("voltage", DEFAULT_VOLTAGE))
        trow = get_class_row(stats, target, row_voltage)
        prow = get_class_row(stats, pred, row_voltage)

        if trow is not None:
            if has_quantiles:
                q05 = get_stats_arr(trow, "q05", base_keys, stats)
                q95 = get_stats_arr(trow, "q95", base_keys, stats)
                q25 = get_stats_arr(trow, "q25", base_keys, stats)
                q75 = get_stats_arr(trow, "q75", base_keys, stats)
                if q05 is not None and q95 is not None:
                    add_band(fig, i, x, q05, q95, TARGET_WIDE_COLOR, f"Target q05-q95 ({target})", showlegend=(i == 1))
                if q25 is not None and q75 is not None:
                    add_band(fig, i, x, q25, q75, TARGET_IQR_COLOR, f"Target IQR ({target})", showlegend=(i == 1))
            targ_med = get_stats_arr(trow, med_suffix, base_keys, stats)
            if targ_med is not None:
                fig.add_trace(
                    go.Scatter(
                        x=x,
                        y=targ_med,
                        mode="lines",
                        line=dict(color=TARGET_LINE_COLOR, width=3),
                        name=f"Target median ({target})",
                        showlegend=(i == 1),
                    ),
                    row=i,
                    col=1,
                )

        if prow is not None:
            if has_quantiles:
                q05 = get_stats_arr(prow, "q05", base_keys, stats)
                q95 = get_stats_arr(prow, "q95", base_keys, stats)
                q25 = get_stats_arr(prow, "q25", base_keys, stats)
                q75 = get_stats_arr(prow, "q75", base_keys, stats)
                if q05 is not None and q95 is not None:
                    add_band(fig, i, x, q05, q95, PRED_WIDE_COLOR, f"Pred q05-q95 ({pred})", showlegend=(i == 1))
                if q25 is not None and q75 is not None:
                    add_band(fig, i, x, q25, q75, PRED_IQR_COLOR, f"Pred IQR ({pred})", showlegend=(i == 1))
            pred_med = get_stats_arr(prow, med_suffix, base_keys, stats)
            if pred_med is not None:
                fig.add_trace(
                    go.Scatter(
                        x=x,
                        y=pred_med,
                        mode="lines",
                        line=dict(color=PRED_LINE_COLOR, width=3),
                        name=f"Pred median ({pred})",
                        showlegend=(i == 1),
                    ),
                    row=i,
                    col=1,
                )

    fig.update_xaxes(
        tickmode="array",
        tickvals=x,
        ticktext=[],
        tickangle=-90,
        title_text="",
        showticklabels=False,
        row=i,
        col=1,
    )
    fig.update_yaxes(title_text="Intensity", row=i, col=1)

fig.update_layout(
    height=380 * len(plot_rows),
    title=f"Top wrong predictions across experiments (top {TOP_N_PER_BUCKET} per experiment/source group)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=60, r=30, t=100, b=180),
)

html_path = BASE_DIR / Path(HTML_OUTPUT_PATH).name
fig.write_html(str(html_path), include_plotlyjs="cdn")
print(f"Saved Plotly HTML: {html_path}")

fig.show()