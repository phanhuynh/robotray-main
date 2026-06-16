"""
Use every row in embeddings_val.npz (no subsampling): metrics, optional 2-D layout,
and CSV summaries.

Example:
  python analyze_embeddings_val.py --npz fuse_inspect_out/embeddings_val.npz
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.manifold import TSNE
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder


def parse_args():
    p = argparse.ArgumentParser(description="Analyze full embeddings_val.npz")
    p.add_argument(
        "--npz",
        type=str,
        default="fuse_inspect_out/embeddings_val.npz",
        help="Path to embeddings_val.npz from inspect_fuse.py",
    )
    p.add_argument(
        "--out-dir",
        type=str,
        default="",
        help="Output directory (default: <npz_dir>/embedding_analysis)",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--skip-tsne",
        action="store_true",
        help="Skip t-SNE plots (faster; still writes CSVs and summary)",
    )
    return p.parse_args()


def softmax_rows(logits: np.ndarray) -> np.ndarray:
    z = logits - logits.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def run_tsne_2d(X: np.ndarray, seed: int) -> np.ndarray | None:
    n = X.shape[0]
    if n < 4:
        print("t-SNE skipped: need at least 4 samples.")
        return None
    perplexity = float(min(30, max(5, (n - 1) // 3)))
    tsne = TSNE(
        n_components=2,
        random_state=seed,
        perplexity=perplexity,
        max_iter=1000,
        init="pca",
        learning_rate="auto",
    )
    return tsne.fit_transform(X.astype(np.float64))


def scatter_2d(xy: np.ndarray, labels: np.ndarray, title: str, out_path: Path):
    enc = LabelEncoder()
    y = enc.fit_transform(labels.astype(str))
    n_classes = len(enc.classes_)

    plt.figure(figsize=(10, 8))
    for c in range(n_classes):
        m = y == c
        plt.scatter(
            xy[m, 0],
            xy[m, 1],
            s=12,
            alpha=0.75,
            label=str(enc.classes_[c]),
            color=f"C{c % 10}",
        )
    plt.legend(bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8, markerscale=2)
    plt.title(title)
    plt.xlabel("dim 1")
    plt.ylabel("dim 2")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_path}")


def main():
    args = parse_args()
    npz_path = Path(args.npz)
    if not npz_path.is_file():
        raise FileNotFoundError(f"Not found: {npz_path.resolve()}")

    out_dir = Path(args.out_dir) if args.out_dir else npz_path.parent / "embedding_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = np.load(npz_path, allow_pickle=True)
    img = np.asarray(data["image_embedding"])
    spec = np.asarray(data["spectra_embedding"])
    logits = np.asarray(data["logits"])
    y_true = np.asarray(data["y_true"], dtype=np.int64)
    y_pred = np.asarray(data["y_pred"], dtype=np.int64)
    label_name = np.asarray(data["label_name"], dtype=object)
    pred_name = np.asarray(data["pred_name"], dtype=object)
    image_path = np.asarray(data["image_path"], dtype=object)

    n = img.shape[0]
    if n != spec.shape[0] or n != logits.shape[0] or n != len(y_true):
        raise ValueError("Mismatched row counts across arrays in npz.")

    labels_sorted = None
    target_names = None
    if "class_to_idx" in data.files:
        pairs = np.asarray(data["class_to_idx"], dtype=object)
        # Saved as list(class_to_idx.items()) -> (class_name, idx)
        name_to_idx = {str(p[0]): int(p[1]) for p in pairs.tolist()}
        idx_to_name = {j: name for name, j in name_to_idx.items()}
        labels_sorted = sorted(idx_to_name.keys())
        target_names = [idx_to_name[i] for i in labels_sorted]

    probs = softmax_rows(logits)
    conf = probs[np.arange(n), y_pred]

    cm = confusion_matrix(y_true, y_pred, labels=labels_sorted) if labels_sorted is not None else confusion_matrix(y_true, y_pred)
    cr = (
        classification_report(
            y_true,
            y_pred,
            labels=labels_sorted,
            target_names=target_names,
            digits=4,
            zero_division=0,
        )
        if target_names is not None
        else classification_report(y_true, y_pred, digits=4, zero_division=0)
    )
    summary_lines = [
        f"npz: {npz_path.resolve()}",
        f"samples: {n}",
        f"image_dim: {img.shape[1]}",
        f"spectra_dim: {spec.shape[1]}",
        f"classes (logits): {logits.shape[1]}",
        f"accuracy: {accuracy_score(y_true, y_pred):.6f}",
        "",
        "confusion_matrix (rows=true, cols=pred):",
        np.array2string(cm, max_line_width=120),
        "",
        "classification_report:",
        cr,
    ]
    summary_path = out_dir / "summary.txt"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"Wrote {summary_path}")

    manifest = pd.DataFrame(
        {
            "image_path": image_path.astype(str),
            "label_name": label_name.astype(str),
            "pred_name": pred_name.astype(str),
            "y_true": y_true,
            "y_pred": y_pred,
            "correct": (y_true == y_pred).astype(np.int32),
            "pred_confidence": conf.astype(np.float64),
        }
    )
    manifest_path = out_dir / "all_samples_manifest.csv"
    manifest.to_csv(manifest_path, index=False)
    print(f"Wrote {manifest_path} ({n} rows)")

    wrong = manifest[manifest["correct"] == 0].copy()
    wrong_path = out_dir / "misclassified.csv"
    wrong.to_csv(wrong_path, index=False)
    print(f"Wrote {wrong_path} ({len(wrong)} rows)")

    if not args.skip_tsne:
        xy_img = run_tsne_2d(img, args.seed)
        if xy_img is not None:
            scatter_2d(xy_img, label_name, "t-SNE — image branch embeddings", out_dir / "tsne_image_embeddings.png")

        xy_spec = run_tsne_2d(spec, args.seed + 1)
        if xy_spec is not None:
            scatter_2d(
                xy_spec,
                label_name,
                "t-SNE — spectra branch embeddings",
                out_dir / "tsne_spectra_embeddings.png",
            )


if __name__ == "__main__":
    main()
