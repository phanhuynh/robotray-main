"""
PyCaret classification workflow (v2): run four recommended experiment designs.

Usage:
    python pycaret_classification_workflow_v2.py

Runs these experiments:
1) Unified base dataset with voltage as categorical feature.
2) Per-voltage separate runs on the base dataset.
3) Mining-only mode-group run.
4) Soil-only mode-group run.
5) All-voltages-wide table (one row per test/target).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pycaret.classification import setup, compare_models, pull, predict_model, finalize_model, save_model
from sklearn.metrics import accuracy_score, f1_score, balanced_accuracy_score, cohen_kappa_score, confusion_matrix


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "df_snr_elem.csv"
OUTPUT_DIR = BASE_DIR / "pycaret_outputs_v2"
SESSION_ID = 123
TARGET_COL = "target"
GROUP_COL = "voltage"
EXPECTED_ENV_NAME = "550_model"
MINING_VOLTAGES = ["mininghighvoltage", "mininglowvoltage"]
SOIL_VOLTAGES = ["soilhighvoltage", "soilmidvoltage", "soillowvoltage"]
CV_FOLDS = 5
N_JOBS = -1
MODEL_SHORTLIST = ["lightgbm", "rf", "et", "lr", "ridge", "knn"]
COMPARE_DIR = OUTPUT_DIR / "_comparison"


def ensure_expected_environment() -> None:
    """
    Fail fast unless this script is running in the required environment.
    Supports both Conda (`CONDA_DEFAULT_ENV`) and venv-style path checks.
    """
    conda_env = os.environ.get("CONDA_DEFAULT_ENV", "").strip()
    venv_path = os.environ.get("VIRTUAL_ENV", "").strip()
    executable_path = str(Path(sys.executable).resolve())

    env_name_candidates = [c for c in [conda_env, Path(venv_path).name] if c]
    path_contains_expected = EXPECTED_ENV_NAME.lower() in executable_path.lower()
    name_matches_expected = any(c.lower() == EXPECTED_ENV_NAME.lower() for c in env_name_candidates)

    if not (name_matches_expected or path_contains_expected):
        raise EnvironmentError(
            "This script must be run in environment '550_model'.\n"
            f"Current python: {sys.executable}\n"
            f"Detected CONDA_DEFAULT_ENV: '{conda_env or '<not set>'}'\n"
            "Activate first, then rerun:\n"
            "  conda activate 550_model"
        )


def load_data(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(f"Input file not found: {csv_path}")
    df = pd.read_csv(csv_path)

    required = {TARGET_COL, GROUP_COL}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    return df


def run_pycaret_once(
    df_in: pd.DataFrame,
    experiment_label: str,
    ignore_features: Optional[List[str]] = None,
    categorical_features: Optional[List[str]] = None,
) -> Dict[str, Any]:
    ignore_features = ignore_features or []
    categorical_features = categorical_features or []

    print(f"\n=== Running experiment: {experiment_label} ===")
    print(f"Rows: {len(df_in):,} | Columns: {df_in.shape[1]}")
    print(df_in[TARGET_COL].value_counts())

    setup_kwargs = dict(
        data=df_in.copy(),
        target=TARGET_COL,
        session_id=SESSION_ID,
        fold=CV_FOLDS,
        n_jobs=N_JOBS,
        use_gpu=False,
        verbose=False,
    )
    if ignore_features:
        setup_kwargs["ignore_features"] = ignore_features
    if categorical_features:
        setup_kwargs["categorical_features"] = categorical_features

    setup(
        **setup_kwargs
    )

    best_model = compare_models(include=MODEL_SHORTLIST, turbo=True)
    leaderboard = pull().copy()
    holdout_preds = predict_model(best_model, raw_score=True)
    final_model = finalize_model(best_model)

    best_row = leaderboard.iloc[0].copy()
    best_row["experiment"] = experiment_label

    return {
        "experiment": experiment_label,
        "best_model": best_model,
        "leaderboard": leaderboard,
        "holdout_predictions": holdout_preds,
        "final_model": final_model,
        "best_metrics": best_row,
    }


def run_per_voltage(df_all: pd.DataFrame) -> tuple[Dict[str, Dict[str, Any]], pd.DataFrame]:
    groups: List[str] = sorted(df_all[GROUP_COL].dropna().astype(str).unique().tolist())
    results: Dict[str, Dict[str, Any]] = {}
    best_rows: List[pd.Series] = []

    for g in groups:
        df_group = df_all[df_all[GROUP_COL].astype(str) == g].copy()
        ignore_features = [c for c in ["test", "session", GROUP_COL] if c in df_group.columns]
        out = run_pycaret_once(
            df_group,
            experiment_label=f"base_voltage_{g}",
            ignore_features=ignore_features,
        )
        results[g] = out
        best_rows.append(out["best_metrics"])

    summary = pd.DataFrame(best_rows)
    metric_cols = [c for c in ["Accuracy", "AUC", "Recall", "Prec.", "F1", "Kappa", "MCC"] if c in summary.columns]
    summary = summary[["experiment", "Model"] + metric_cols]
    summary = summary.sort_values(by="Accuracy", ascending=False).reset_index(drop=True)
    return results, summary


def build_mode_group_no_nan(df_in: pd.DataFrame, voltage_list: List[str], new_label: str) -> pd.DataFrame:
    d = df_in[df_in[GROUP_COL].isin(voltage_list)].copy()
    meta_cols = ["test", "target", "voltage"]
    feature_cols = [c for c in d.columns if c not in meta_cols]

    wide = d.pivot_table(
        index=["test", "target"],
        columns="voltage",
        values=feature_cols,
        aggfunc="first",
    )
    wide.columns = [f"{feat}_{volt}" for feat, volt in wide.columns]
    wide = wide.reset_index()
    wide.insert(0, "voltage", new_label)

    keep_cols = ["voltage", "test", "target"] + [
        c for c in wide.columns if any(c.endswith(f"_{v}") for v in voltage_list)
    ]
    return wide[keep_cols]


def build_all_voltages_wide(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    Build one-row-per-(test,target) table by pivoting all voltages into columns.
    Resulting columns look like <feature>_<voltage>.
    """
    meta_cols = ["test", "target", "voltage"]
    feature_cols = [c for c in df_in.columns if c not in meta_cols]

    wide = df_in.pivot_table(
        index=["test", "target"],
        columns="voltage",
        values=feature_cols,
        aggfunc="first",
    )
    wide.columns = [f"{feat}_{volt}" for feat, volt in wide.columns]
    wide = wide.reset_index()
    return wide


def _extract_y_true_pred(preds: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    if "target" not in preds.columns or "prediction_label" not in preds.columns:
        raise ValueError("Expected columns 'target' and 'prediction_label' in prediction output.")
    y_true = preds["target"].astype(str)
    y_pred = preds["prediction_label"].astype(str)
    return y_true, y_pred


def _save_confusion_artifacts(
    y_true: pd.Series,
    y_pred: pd.Series,
    labels: List[str],
    output_dir: Path,
    stem: str,
) -> None:
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    cm_df = pd.DataFrame(cm, index=labels, columns=labels)
    cm_df.to_csv(output_dir / f"{stem}_confusion_matrix.csv")

    # Row-normalized confusion matrix.
    with np.errstate(invalid="ignore", divide="ignore"):
        row_sums = cm.sum(axis=1, keepdims=True)
        cm_norm = np.divide(cm, row_sums, where=row_sums != 0)
    cm_norm_df = pd.DataFrame(cm_norm, index=labels, columns=labels)
    cm_norm_df.to_csv(output_dir / f"{stem}_confusion_matrix_normalized.csv")

    try:
        fig, ax = plt.subplots(figsize=(8, 6))
        im = ax.imshow(cm_norm, interpolation="nearest", cmap="Blues")
        ax.figure.colorbar(im, ax=ax)
        ax.set(
            xticks=np.arange(len(labels)),
            yticks=np.arange(len(labels)),
            xticklabels=labels,
            yticklabels=labels,
            ylabel="True label",
            xlabel="Predicted label",
            title=f"{stem} (normalized confusion matrix)",
        )
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
        fig.tight_layout()
        fig.savefig(output_dir / f"{stem}_confusion_matrix_normalized.png", dpi=150)
        plt.close(fig)
    except Exception as exc:
        # Keep run resilient even when plotting backend/env is unstable.
        print(f"Warning: could not render confusion matrix PNG for '{stem}': {exc}")


def summarize_predictions(
    experiment_name: str,
    preds: pd.DataFrame,
    output_dir: Path,
    labels: List[str],
    records: List[Dict[str, Any]],
) -> None:
    y_true, y_pred = _extract_y_true_pred(preds)
    record = {
        "experiment": experiment_name,
        "holdout_rows": len(preds),
        "accuracy": accuracy_score(y_true, y_pred),
        "balanced_accuracy": balanced_accuracy_score(y_true, y_pred),
        "f1_macro": f1_score(y_true, y_pred, average="macro", zero_division=0),
        "f1_weighted": f1_score(y_true, y_pred, average="weighted", zero_division=0),
        "kappa": cohen_kappa_score(y_true, y_pred),
    }
    records.append(record)
    _save_confusion_artifacts(y_true, y_pred, labels, output_dir, experiment_name)


def _wrong_predictions_from_preds(preds: pd.DataFrame) -> pd.DataFrame:
    """Return wrong predictions with pred/true probabilities and margin (%)."""
    preds = preds.copy()
    required_cols = {"target", "prediction_label"}
    missing_required = required_cols - set(preds.columns)
    if missing_required:
        raise ValueError(f"Missing required prediction columns: {sorted(missing_required)}")

    score_cols = [c for c in preds.columns if c.startswith("prediction_score_")]
    class_to_col = {c.replace("prediction_score_", ""): c for c in score_cols}

    def prob_for_label(row: pd.Series, label: Any) -> float:
        col = class_to_col.get(str(label))
        return float(row[col]) if col in row else np.nan

    preds["pred_prob"] = preds.apply(lambda r: prob_for_label(r, r["prediction_label"]), axis=1)
    preds["true_prob"] = preds.apply(lambda r: prob_for_label(r, r["target"]), axis=1)
    preds["wrong_margin"] = preds["pred_prob"] - preds["true_prob"]

    wrong = preds[preds["target"].astype(str) != preds["prediction_label"].astype(str)].copy()
    wrong = wrong.sort_values("wrong_margin", ascending=False)

    for c in score_cols + ["pred_prob", "true_prob", "wrong_margin"]:
        if c in wrong.columns:
            wrong[c] = wrong[c] * 100.0

    return wrong


def export_combined_wrong_predictions(
    unified: Dict[str, Any],
    per_voltage_results: Dict[str, Dict[str, Any]],
    mining_run: Dict[str, Any],
    soil_run: Dict[str, Any],
    wide_run: Dict[str, Any],
    output_path: Path,
) -> None:
    """
    Export wrong predictions from all five experiment designs into one file.
    Adds metadata columns so downstream plotting can filter by experiment.
    """
    frames: List[pd.DataFrame] = []

    def append_wrong(experiment_name: str, preds: pd.DataFrame, source_group: str = "") -> None:
        wrong = _wrong_predictions_from_preds(preds)
        wrong.insert(0, "source_group", source_group)
        wrong.insert(0, "experiment", experiment_name)
        frames.append(wrong)

    append_wrong("unified_base_with_voltage_categorical", unified["holdout_predictions"])
    append_wrong("mode_group_mining", mining_run["holdout_predictions"])
    append_wrong("mode_group_soil", soil_run["holdout_predictions"])
    append_wrong("all_voltages_wide_one_row_per_test", wide_run["holdout_predictions"])

    for group_name, out in per_voltage_results.items():
        append_wrong("per_voltage", out["holdout_predictions"], source_group=group_name)

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined.sort_values(
        by=["experiment", "source_group", "wrong_margin"],
        ascending=[True, True, False],
    ).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)
    print(f"Exported combined wrong predictions: {output_path}")
    print(f"Wrong rows exported (all experiments): {len(combined)}")


def build_comparison_artifacts(
    unified: Dict[str, Any],
    per_voltage_results: Dict[str, Dict[str, Any]],
    mining_run: Dict[str, Any],
    soil_run: Dict[str, Any],
    wide_run: Dict[str, Any],
) -> None:
    COMPARE_DIR.mkdir(parents=True, exist_ok=True)
    labels = sorted(
        set(
            unified["holdout_predictions"]["target"].astype(str).unique().tolist()
            + wide_run["holdout_predictions"]["target"].astype(str).unique().tolist()
        )
    )
    metric_rows: List[Dict[str, Any]] = []

    summarize_predictions(
        "unified_base_with_voltage_categorical",
        unified["holdout_predictions"],
        COMPARE_DIR,
        labels,
        metric_rows,
    )
    summarize_predictions(
        "mode_group_mining",
        mining_run["holdout_predictions"],
        COMPARE_DIR,
        labels,
        metric_rows,
    )
    summarize_predictions(
        "mode_group_soil",
        soil_run["holdout_predictions"],
        COMPARE_DIR,
        labels,
        metric_rows,
    )
    summarize_predictions(
        "all_voltages_wide_one_row_per_test",
        wide_run["holdout_predictions"],
        COMPARE_DIR,
        labels,
        metric_rows,
    )

    # Per-voltage: save individual plus aggregate.
    per_voltage_dir = COMPARE_DIR / "per_voltage"
    per_voltage_dir.mkdir(parents=True, exist_ok=True)
    per_voltage_frames = []
    for group_name, out in per_voltage_results.items():
        exp_name = f"per_voltage_{group_name}"
        preds = out["holdout_predictions"]
        per_voltage_frames.append(preds)
        summarize_predictions(exp_name, preds, per_voltage_dir, labels, metric_rows)

    per_voltage_all = pd.concat(per_voltage_frames, ignore_index=True)
    summarize_predictions(
        "per_voltage_aggregated",
        per_voltage_all,
        COMPARE_DIR,
        labels,
        metric_rows,
    )

    comparison_df = pd.DataFrame(metric_rows).sort_values("accuracy", ascending=False).reset_index(drop=True)
    comparison_df.to_csv(COMPARE_DIR / "metrics_comparison.csv", index=False)
    print(f"\nSaved comparison artifacts to: {COMPARE_DIR}")
    print(f"Comparison metrics: {COMPARE_DIR / 'metrics_comparison.csv'}")


def persist_outputs(results: Dict[str, Dict[str, Any]], summary: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_path = output_dir / "summary.csv"
    summary.to_csv(summary_path, index=False)

    for group_name, out in results.items():
        safe_group = group_name.replace("/", "_").replace("\\", "_").replace(" ", "_")

        leaderboard_path = output_dir / f"leaderboard_{safe_group}.csv"
        holdout_path = output_dir / f"holdout_predictions_{safe_group}.csv"
        model_path = output_dir / f"final_model_{safe_group}"

        out["leaderboard"].to_csv(leaderboard_path, index=False)
        out["holdout_predictions"].to_csv(holdout_path, index=False)
        save_model(out["final_model"], str(model_path))

    print(f"\nSaved outputs to: {output_dir}")
    print(f"Summary file: {summary_path}")


def main() -> None:
    ensure_expected_environment()

    df = load_data(DATA_PATH)
    print(f"Loaded data: {DATA_PATH}")
    print(f"Shape: {df.shape}")

    # 1) Unified base dataset with voltage as categorical feature
    unified_ignore = [c for c in ["test", "session"] if c in df.columns]
    unified = run_pycaret_once(
        df,
        experiment_label="unified_base_with_voltage_categorical",
        ignore_features=unified_ignore,
        categorical_features=["voltage"],
    )
    unified_summary = pd.DataFrame([unified["best_metrics"]])
    unified_summary = unified_summary[["experiment", "Model", "Accuracy", "AUC", "Recall", "Prec.", "F1", "Kappa", "MCC"]]
    persist_outputs({"unified": unified}, unified_summary, OUTPUT_DIR / "unified_base_with_voltage_categorical")

    # 2) Per-voltage separate runs on base dataset
    per_voltage_results, per_voltage_summary = run_per_voltage(df)
    persist_outputs(per_voltage_results, per_voltage_summary, OUTPUT_DIR / "per_voltage")

    # 3 and 4) Mode-grouped runs (separate mining and soil)
    df_mining = build_mode_group_no_nan(df, MINING_VOLTAGES, "mining")
    df_soil = build_mode_group_no_nan(df, SOIL_VOLTAGES, "soil")

    mining_run = run_pycaret_once(df_mining.drop(columns=["voltage"]), "mode_group_mining")
    soil_run = run_pycaret_once(df_soil.drop(columns=["voltage"]), "mode_group_soil")
    mode_summary = pd.DataFrame([mining_run["best_metrics"], soil_run["best_metrics"]])
    mode_summary = mode_summary[["experiment", "Model", "Accuracy", "AUC", "Recall", "Prec.", "F1", "Kappa", "MCC"]]
    persist_outputs(
        {"mining": mining_run, "soil": soil_run},
        mode_summary.sort_values(by="Accuracy", ascending=False).reset_index(drop=True),
        OUTPUT_DIR / "mode_group_separate_runs",
    )

    # 5) All voltages on one wide row per (test, target)
    df_all_voltages_wide = build_all_voltages_wide(df)
    print("\nAll-voltages-wide table shape:", df_all_voltages_wide.shape)
    wide_run = run_pycaret_once(
        df_all_voltages_wide,
        experiment_label="all_voltages_wide_one_row_per_test",
        ignore_features=["test"],
    )
    wide_summary = pd.DataFrame([wide_run["best_metrics"]])
    wide_summary = wide_summary[["experiment", "Model", "Accuracy", "AUC", "Recall", "Prec.", "F1", "Kappa", "MCC"]]
    persist_outputs(
        {"all_voltages_wide": wide_run},
        wide_summary,
        OUTPUT_DIR / "all_voltages_wide_one_row_per_test",
    )

    export_combined_wrong_predictions(
        unified=unified,
        per_voltage_results=per_voltage_results,
        mining_run=mining_run,
        soil_run=soil_run,
        wide_run=wide_run,
        output_path=BASE_DIR / "wrong_predictions.csv",
    )

    build_comparison_artifacts(
        unified=unified,
        per_voltage_results=per_voltage_results,
        mining_run=mining_run,
        soil_run=soil_run,
        wide_run=wide_run,
    )

    print("\n=== Completed all five experiment designs ===")
    print("1) unified_base_with_voltage_categorical")
    print("2) per_voltage")
    print("3) mode_group_mining")
    print("4) mode_group_soil")
    print("5) all_voltages_wide_one_row_per_test")
    print("\nNote: PyCaret evaluate_model dashboard is interactive and can only be viewed one model at a time.")
    print("Use saved confusion matrix PNG/CSV files in pycaret_outputs_v2/_comparison for side-by-side comparison.")


if __name__ == "__main__":
    main()
