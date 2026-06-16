from __future__ import annotations

from pathlib import Path
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px


DEFAULT_PARENT_DIR = Path(
    r"C:\Users\phuynh\Projects\robotray-main\robotray_v2\sample_outputs_v2"
)


def _first_mining_high_voltage_csv(folder: Path) -> Path | None:
    matches = sorted(folder.glob("*MiningHighVoltage*.csv"))
    return matches[0] if matches else None


def _read_energy_column(csv_path: Path) -> np.ndarray | None:
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None

    if "Energy (keV)" not in df.columns:
        return None

    energy = pd.to_numeric(df["Energy (keV)"], errors="coerce").dropna().to_numpy()
    if energy.size == 0:
        return None
    return energy


def main(parent_dir: Path = DEFAULT_PARENT_DIR) -> int:
    parent_dir = Path(parent_dir)
    if not parent_dir.exists():
        print(f"ERROR: parent_dir not found: {parent_dir}")
        return 2

    per_folder: list[tuple[Path, Path, np.ndarray]] = []
    for root, _, _ in os.walk(parent_dir):
        folder = Path(root)
        csv_path = _first_mining_high_voltage_csv(folder)
        if csv_path is None:
            continue

        energy = _read_energy_column(csv_path)
        if energy is None:
            print(f"skipped (missing/invalid Energy column): {csv_path}")
            continue

        per_folder.append((folder, csv_path, energy))

    if not per_folder:
        print(f"No MiningHighVoltage CSVs with 'Energy (keV)' found under {parent_dir}")
        return 1

    output_dir = Path(__file__).resolve().parent

    # Interactive alignment plot: each folder gets its own color + legend entry.
    labels = [folder.relative_to(parent_dir).as_posix() for folder, _, _ in per_folder]
    palette = px.colors.qualitative.Dark24 + px.colors.qualitative.Light24

    fig = go.Figure()
    for i, (folder, csv_path, energy) in enumerate(per_folder):
        label = labels[i]
        fig.add_trace(
            go.Scattergl(
                x=energy,
                y=np.zeros_like(energy, dtype=float),
                mode="markers",
                name=label,
                marker=dict(size=4, opacity=0.5, color=palette[i % len(palette)]),
                hovertemplate=(
                    "folder=%{text}<br>"
                    "energy=%{x:.5f} keV<br>"
                    "<extra></extra>"
                ),
                text=[label] * int(energy.size),
            )
        )

    fig.update_layout(
        title=f"Energy (keV) alignment across MiningHighVoltage CSVs<br><sup>{parent_dir}</sup>",
        xaxis_title="Energy (keV)",
        yaxis=dict(title="", showticklabels=False, zeroline=True, zerolinewidth=1),
        template="plotly_white",
        legend=dict(itemsizing="constant"),
        margin=dict(l=60, r=30, t=80, b=50),
        height=600,
    )

    out_html = output_dir / "check_energy_lines.html"
    fig.write_html(out_html, include_plotlyjs="cdn")

    summary_rows = []
    for folder, csv_path, energy in per_folder:
        diffs = np.diff(energy) if energy.size >= 2 else np.array([])
        summary_rows.append(
            {
                "folder": str(folder),
                "csv": str(csv_path),
                "n": int(energy.size),
                "energy_min": float(np.min(energy)),
                "energy_max": float(np.max(energy)),
                "energy_mean": float(np.mean(energy)),
                "energy_std": float(np.std(energy)),
                "step_mean": float(np.mean(diffs)) if diffs.size else np.nan,
                "step_std": float(np.std(diffs)) if diffs.size else np.nan,
            }
        )

    out_csv = output_dir / "check_energy_lines_summary.csv"
    pd.DataFrame(summary_rows).sort_values(["folder", "csv"]).to_csv(out_csv, index=False)

    print(f"Matched folders: {len(per_folder)}")
    print(f"Saved plot: {out_html}")
    print(f"Saved summary: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

