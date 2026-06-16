from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd
import plotly.express as px


BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "pycaret_outputs_v2"
COMPARE_DIR = OUT_DIR / "_comparison"
DASHBOARD_PATH = BASE_DIR / "performance_dashboard.html"

METRIC_COLS = ["Accuracy", "AUC", "Recall", "Prec.", "F1", "Kappa", "MCC"]
TOP_K = 3
PRIMARY_METRIC = "Prec."


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    return pd.read_csv(path)


def _top_k(df: pd.DataFrame, k: int = TOP_K) -> pd.DataFrame:
    cols = ["Model"] + [c for c in METRIC_COLS if c in df.columns]
    out = df[cols].copy()
    sort_col = PRIMARY_METRIC if PRIMARY_METRIC in out.columns else "Accuracy"
    out = out.sort_values(sort_col, ascending=False).head(k).reset_index(drop=True)
    out.insert(0, "Rank", range(1, len(out) + 1))
    return out


def _build_per_voltage_top3_tables() -> Dict[str, pd.DataFrame]:
    files = sorted((OUT_DIR / "per_voltage").glob("leaderboard_*.csv"))
    if not files:
        raise FileNotFoundError("No per-voltage leaderboard files found.")

    tables: Dict[str, pd.DataFrame] = {}
    for f in files:
        df = _read_csv(f)
        group = f.stem.replace("leaderboard_", "")
        tables[f"per_voltage_{group}"] = _top_k(df, TOP_K)
    return tables


def build_tables() -> Dict[str, pd.DataFrame]:
    tables = {
        "unified_base_with_voltage_categorical": _top_k(
            _read_csv(OUT_DIR / "unified_base_with_voltage_categorical" / "leaderboard_unified.csv")
        ),
        "mode_group_mining": _top_k(_read_csv(OUT_DIR / "mode_group_separate_runs" / "leaderboard_mining.csv")),
        "mode_group_soil": _top_k(_read_csv(OUT_DIR / "mode_group_separate_runs" / "leaderboard_soil.csv")),
        "all_voltages_wide_one_row_per_test": _top_k(
            _read_csv(OUT_DIR / "all_voltages_wide_one_row_per_test" / "leaderboard_all_voltages_wide.csv")
        ),
    }
    tables.update(_build_per_voltage_top3_tables())
    return tables


def build_overall_chart(top_tables: Dict[str, pd.DataFrame]) -> str:
    rows: List[dict] = []
    for exp, t in top_tables.items():
        for _, r in t.iterrows():
            rows.append(
                {
                    "experiment": exp,
                    "rank": int(r["Rank"]),
                    "model": r["Model"],
                    "primary_metric": float(r[PRIMARY_METRIC]) if PRIMARY_METRIC in r else float(r["Accuracy"]),
                }
            )
    df = pd.DataFrame(rows)
    fig = px.bar(
        df,
        x="experiment",
        y="primary_metric",
        color="model",
        barmode="group",
        text="rank",
        title=f"Top {TOP_K} Models Per Experiment ({PRIMARY_METRIC})",
    )
    fig.update_traces(texttemplate="rank %{text}", textposition="outside")
    fig.update_layout(xaxis_title="", yaxis_title=PRIMARY_METRIC)
    return fig.to_html(full_html=False, include_plotlyjs="cdn")


def _table_html(df: pd.DataFrame) -> str:
    return df.to_html(index=False, classes="tbl", float_format=lambda x: f"{x:.4f}")


def _confusion_links_html(experiment_key: str) -> str:
    # Map dashboard section names to confusion artifact stems.
    stem_map = {
        "unified_base_with_voltage_categorical": "unified_base_with_voltage_categorical",
        "mode_group_mining": "mode_group_mining",
        "mode_group_soil": "mode_group_soil",
        "all_voltages_wide_one_row_per_test": "all_voltages_wide_one_row_per_test",
    }
    if experiment_key.startswith("per_voltage_"):
        per_name = experiment_key.replace("per_voltage_", "")
        files = sorted((COMPARE_DIR / "per_voltage").glob(f"per_voltage_{per_name}*confusion_matrix*.csv"))
    else:
        stem = stem_map[experiment_key]
        files = sorted(COMPARE_DIR.glob(f"{stem}*confusion_matrix*.csv"))

    if not files:
        return "<p>No confusion matrix files found.</p>"

    links = []
    for f in files:
        rel = f.relative_to(BASE_DIR).as_posix()
        links.append(f'<li><a href="{rel}" target="_blank">{f.name}</a></li>')
    return "<ul>" + "".join(links) + "</ul>"


def _render_confusion_matrix_html(cm: pd.DataFrame) -> str:
    """Render a normalized confusion matrix as a heatmap-like HTML table."""
    cm = cm.apply(pd.to_numeric, errors="coerce").fillna(0.0)

    max_val = float(cm.to_numpy().max()) if len(cm) else 1.0
    max_val = max(max_val, 1e-9)

    header = "<tr><th>true \\ pred</th>" + "".join(f"<th>{c}</th>" for c in cm.columns) + "</tr>"
    body_rows: List[str] = []
    for r_label, row in cm.iterrows():
        cells = []
        for _, v in row.items():
            norm = float(v) / max_val
            blue = int(235 - 120 * norm)
            red_green = int(245 - 180 * norm)
            bg = f"rgb({red_green},{red_green},{blue})"
            text_color = "#000" if norm < 0.6 else "#fff"
            cell_style = f' style="background:{bg};color:{text_color};text-align:center;"'
            cells.append(f"<td{cell_style}>{100.0 * float(v):.1f}%</td>")
        body_rows.append(f"<tr><th>{r_label}</th>{''.join(cells)}</tr>")
    return f'<table class="tbl">{header}{"".join(body_rows)}</table>'


def _all_per_voltage_confusion_html() -> str:
    summary_path = OUT_DIR / "per_voltage" / "summary.csv"
    if not summary_path.exists():
        return "<p>Missing per_voltage summary.csv.</p>"

    summary = pd.read_csv(summary_path)
    if "experiment" not in summary.columns or "Prec." not in summary.columns:
        return "<p>per_voltage summary.csv is missing expected columns.</p>"

    per_rows = summary[summary["experiment"].astype(str).str.startswith("base_voltage_")].copy()
    if per_rows.empty:
        return "<p>No base_voltage rows found in per_voltage summary.</p>"

    per_rows["Prec."] = pd.to_numeric(per_rows["Prec."], errors="coerce")
    per_rows["group"] = per_rows["experiment"].astype(str).str.replace("base_voltage_", "", regex=False)
    per_rows = per_rows.sort_values("Prec.", ascending=True).reset_index(drop=True)

    blocks: List[str] = ["<p>Normalized confusion matrices (rows sum to 100%), sorted by lowest Precision first.</p>"]
    for _, r in per_rows.iterrows():
        group = str(r["group"])
        precision = float(r["Prec."])
        cm_path = COMPARE_DIR / "per_voltage" / f"per_voltage_{group}_confusion_matrix_normalized.csv"
        if not cm_path.exists():
            blocks.append(f"<p><strong>{group}</strong> (Precision={precision:.4f}) - missing confusion matrix file.</p>")
            continue
        cm = pd.read_csv(cm_path, index_col=0)
        blocks.append(f"<h3>{group} (Precision={precision:.4f})</h3>")
        blocks.append(_render_confusion_matrix_html(cm))
    return "".join(blocks)


def build_html(top_tables: Dict[str, pd.DataFrame]) -> str:
    chart_html = build_overall_chart(top_tables)

    sections = []
    for exp, table in top_tables.items():
        sections.append(
            f"""
            <section>
              <h2>{exp}</h2>
              <h3>Top {TOP_K} Models</h3>
              {_table_html(table)}
              <h3>Confusion Matrix Artifacts</h3>
              {_confusion_links_html(exp)}
              <h3>Interactive PyCaret Dashboard</h3>
              <pre>from pycaret.classification import evaluate_model
# rerun/load the corresponding best model for this experiment:
evaluate_model(best_model)</pre>
            </section>
            """
        )

    all_per_voltage_section = f"""
    <section>
      <h2>All per_voltage Confusion Matrices</h2>
      {_all_per_voltage_confusion_html()}
    </section>
    """

    style = """
    <style>
      body { font-family: Arial, sans-serif; margin: 24px; }
      h1, h2, h3 { margin-bottom: 8px; }
      section { margin-top: 28px; padding-top: 12px; border-top: 1px solid #ddd; }
      .tbl { border-collapse: collapse; width: 100%; margin: 8px 0 16px 0; }
      .tbl th, .tbl td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; }
      .tbl th { background: #f5f5f5; }
      pre { background: #f8f8f8; border: 1px solid #eee; padding: 10px; }
    </style>
    """

    return f"""
    <html>
      <head>
        <meta charset="utf-8" />
        <title>PyCaret Experiment Performance Dashboard</title>
        {style}
      </head>
      <body>
        <h1>PyCaret Experiment Performance Dashboard</h1>
        <p>Shows top-{TOP_K} models by experiment ranked by {PRIMARY_METRIC}, and links to confusion artifacts.</p>
        {chart_html}
        {all_per_voltage_section}
        {''.join(sections)}
      </body>
    </html>
    """


def main() -> None:
    top_tables = build_tables()
    html = build_html(top_tables)
    DASHBOARD_PATH.write_text(html, encoding="utf-8")
    print(f"Saved dashboard: {DASHBOARD_PATH}")


if __name__ == "__main__":
    main()

