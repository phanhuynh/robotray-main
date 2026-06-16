"""
Load a trained fusion checkpoint, export validation embeddings, and save Grad-CAM
overlays for the image branch (ResNet layer4).

Example:
  python inspect_fuse.py --checkpoint mineral_fusion_resnet18_spectra.pth --out-dir fuse_inspect_out
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader

from train_fuse import (
    EarlyFusionNet,
    FusionDataset,
    IMAGE_DIR,
    IMG_SIZE,
    NUM_WORKERS,
    RANDOM_SEED,
    SPECTRA_CSV,
    build_spectra_map,
    collect_images_by_key,
    make_examples_from_keys,
    set_seed,
)
from torchvision import transforms


IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
IMAGENET_STD = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)


def parse_args():
    p = argparse.ArgumentParser(description="Fusion model inspection: embeddings + Grad-CAM")
    p.add_argument(
        "--checkpoint",
        type=str,
        default="mineral_fusion_resnet18_spectra.pth",
        help="Path to torch.save dict from train_fuse.py",
    )
    p.add_argument("--out-dir", type=str, default="fuse_inspect_out", help="Output directory")
    p.add_argument("--image-dir", type=str, default=IMAGE_DIR)
    p.add_argument("--spectra-csv", type=str, default=SPECTRA_CSV)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--max-embed", type=int, default=0, help="Max val samples for npz (0 = all)")
    p.add_argument("--gradcam-n", type=int, default=24, help="Number of Grad-CAM images to save")
    p.add_argument("--seed", type=int, default=RANDOM_SEED)
    p.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    return p.parse_args()


def build_val_split(image_dir: str, spectra_csv: str, seed: int):
    """Same key filtering and train/val split as train_fuse.main (must match training)."""
    key_to_images, key_to_label = collect_images_by_key(image_dir)
    key_to_spectra, key_to_target, _, _ = build_spectra_map(spectra_csv)

    common_keys = sorted(set(key_to_images).intersection(key_to_spectra))
    if not common_keys:
        raise RuntimeError("No overlapping sample keys.")

    valid_keys = [k for k in common_keys if key_to_label[k] == key_to_target[k]]
    if len(valid_keys) < 2:
        raise RuntimeError("Too few valid keys.")

    key_labels = [key_to_label[k] for k in valid_keys]
    train_keys, val_keys = train_test_split(
        valid_keys,
        test_size=0.2,
        random_state=seed,
        stratify=key_labels,
    )

    val_paths, val_labels, val_specs_raw = make_examples_from_keys(
        val_keys, key_to_images, key_to_label, key_to_spectra
    )
    return val_paths, val_labels, val_specs_raw


def apply_saved_scaler(specs: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    s = scale.copy()
    s[s == 0] = 1.0
    return ((specs - mean) / s).astype(np.float32)


def denormalize_image(t: torch.Tensor) -> np.ndarray:
    """t: (3,H,W) tensor on CPU."""
    x = t * IMAGENET_STD + IMAGENET_MEAN
    x = x.clamp(0, 1).numpy().transpose(1, 2, 0)
    return x


def overlay_gradcam(rgb: np.ndarray, cam: np.ndarray, alpha: float = 0.45) -> np.ndarray:
    """rgb, cam in [0,1], HxWx3 and HxW."""
    heat = plt.get_cmap("jet")(cam)[..., :3]
    return np.clip((1 - alpha) * rgb + alpha * heat, 0, 1)


def compute_gradcam_layer4(
    model: EarlyFusionNet,
    images: torch.Tensor,
    spectra: torch.Tensor,
    target_class: int,
    device: str,
) -> np.ndarray:
    """
    Grad-CAM on image_backbone.layer4 for the given target class index.
    images: (1,3,H,W), requires_grad should be True on images.
    Returns: cam (H, W) float in [0, 1].
    """
    activations = []
    gradients = []

    def fwd_hook(module, inp, out):
        activations.append(out)

    def bwd_hook(module, grad_in, grad_out):
        gradients.append(grad_out[0])

    layer = model.image_backbone.layer4
    h1 = layer.register_forward_hook(fwd_hook)
    h2 = layer.register_full_backward_hook(bwd_hook)

    model.zero_grad(set_to_none=True)
    logits = model(images, spectra)
    score = logits[0, target_class]
    score.backward()

    h1.remove()
    h2.remove()

    act = activations[0][0]
    grad = gradients[0][0]

    weights = grad.mean(dim=(1, 2), keepdim=True)
    cam = (weights * act).sum(dim=0)
    cam = F.relu(cam)
    cam = cam.unsqueeze(0).unsqueeze(0)
    cam = F.interpolate(cam, size=(images.shape[2], images.shape[3]), mode="bilinear", align_corners=False)
    cam = cam.squeeze().detach().cpu().numpy()
    cmin, cmax = cam.min(), cam.max()
    if cmax - cmin > 1e-8:
        cam = (cam - cmin) / (cmax - cmin)
    else:
        cam = np.zeros_like(cam)
    return cam


@torch.no_grad()
def collect_embeddings(model, loader, device, max_samples: int):
    """Hooks on full image_backbone (512-D) and spectra_mlp (128-D) outputs."""
    img_chunks, spec_chunks, log_chunks = [], [], []
    y_true, y_pred, paths = [], [], []

    def img_hook(mod, inp, out):
        img_chunks.append(out.detach().cpu())

    def spec_hook(mod, inp, out):
        spec_chunks.append(out.detach().cpu())

    h_img = model.image_backbone.register_forward_hook(img_hook)
    h_spec = model.spectra_mlp.register_forward_hook(spec_hook)

    model.eval()
    global_idx = 0
    for images, spectra, targets in loader:
        if max_samples and global_idx >= max_samples:
            break

        images = images.to(device)
        spectra = spectra.to(device)
        logits = model(images, spectra)
        preds = logits.argmax(dim=1)
        bs = images.size(0)

        if max_samples:
            take = min(bs, max_samples - global_idx)
        else:
            take = bs

        for j in range(take):
            paths.append(loader.dataset.image_paths[global_idx + j])
            y_true.append(int(targets[j].item()))
            y_pred.append(int(preds[j].item()))

        log_chunks.append(logits[:take].detach().cpu())
        img_chunks[-1] = img_chunks[-1][:take]
        spec_chunks[-1] = spec_chunks[-1][:take]

        global_idx += take

    h_img.remove()
    h_spec.remove()

    img_emb = torch.cat(img_chunks, dim=0).numpy()
    spec_emb = torch.cat(spec_chunks, dim=0).numpy()
    logits_np = torch.cat(log_chunks, dim=0).numpy()
    return img_emb, spec_emb, logits_np, np.array(y_true), np.array(y_pred), np.array(paths, dtype=object)


def save_gradcam_batch(
    model,
    val_paths,
    val_specs,
    val_labels,
    class_to_idx,
    idx_to_class,
    val_tf,
    device,
    out_dir: Path,
    n: int,
    seed: int,
):
    rng = random.Random(seed)
    indices = list(range(len(val_paths)))
    rng.shuffle(indices)
    indices = indices[:n]

    grad_dir = out_dir / "gradcam"
    grad_dir.mkdir(parents=True, exist_ok=True)

    model.eval()
    for k, idx in enumerate(indices):
        path = val_paths[idx]
        spec = torch.from_numpy(val_specs[idx]).unsqueeze(0).to(device)
        label_str = val_labels[idx]
        y = class_to_idx[label_str]

        pil = Image.open(path).convert("RGB")
        img_tensor = val_tf(pil).unsqueeze(0).to(device)
        img_tensor.requires_grad_(True)

        with torch.enable_grad():
            logits = model(img_tensor, spec)
            pred = int(logits.argmax(dim=1).item())

        cam = compute_gradcam_layer4(model, img_tensor, spec, pred, device)

        img_cpu = val_tf(pil).cpu()
        rgb = denormalize_image(img_cpu[0])
        overlay = overlay_gradcam(rgb, cam)

        base = f"{k:03d}_idx{idx}_true-{label_str}_pred-{idx_to_class[pred]}"
        plt.imsave(grad_dir / f"{base}_overlay.png", overlay)
        plt.imsave(grad_dir / f"{base}_cam.png", cam, cmap="jet")

    print(f"Saved {len(indices)} Grad-CAM pairs to {grad_dir}")


def main():
    args = parse_args()
    set_seed(args.seed)
    device = args.device
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ckpt_path = Path(args.checkpoint)
    if not ckpt_path.is_file():
        raise FileNotFoundError(f"Checkpoint not found: {ckpt_path.resolve()}")

    try:
        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    except TypeError:
        ckpt = torch.load(ckpt_path, map_location="cpu")
    class_to_idx = ckpt["class_to_idx"]
    idx_to_class = {int(k): v for k, v in ckpt["idx_to_class"].items()}
    mean = np.asarray(ckpt["scaler_mean"], dtype=np.float32)
    scale = np.asarray(ckpt["scaler_scale"], dtype=np.float32)
    spectra_cols = ckpt.get("spectra_columns", [])
    voltage_order = ckpt.get("spectra_voltage_order", [])

    val_paths, val_labels, val_specs_raw = build_val_split(args.image_dir, args.spectra_csv, args.seed)
    val_specs = apply_saved_scaler(val_specs_raw, mean, scale)

    val_tf = transforms.Compose(
        [
            transforms.Resize((IMG_SIZE, IMG_SIZE)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )

    num_classes = len(class_to_idx)
    spectra_dim = val_specs.shape[1]
    model = EarlyFusionNet(num_classes=num_classes, spectra_dim=spectra_dim)
    model.load_state_dict(ckpt["model_state_dict"])
    model = model.to(device)

    val_ds = FusionDataset(val_paths, val_specs, val_labels, class_to_idx, transform=val_tf)
    val_loader = DataLoader(
        val_ds,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=NUM_WORKERS,
    )

    max_e = args.max_embed if args.max_embed > 0 else 0
    img_emb, spec_emb, logits_np, y_true, y_pred, paths = collect_embeddings(
        model, val_loader, device, max_e
    )

    label_names = np.array([idx_to_class[i] for i in y_true], dtype=object)
    pred_names = np.array([idx_to_class[i] for i in y_pred], dtype=object)

    npz_path = out_dir / "embeddings_val.npz"
    np.savez_compressed(
        npz_path,
        image_embedding=img_emb,
        spectra_embedding=spec_emb,
        logits=logits_np,
        y_true=y_true,
        y_pred=y_pred,
        label_name=label_names,
        pred_name=pred_names,
        image_path=paths,
        class_to_idx=np.array(list(class_to_idx.items()), dtype=object),
        spectra_columns=np.array(spectra_cols, dtype=object),
        spectra_voltage_order=np.array(voltage_order, dtype=object),
    )
    print(f"Saved embeddings: {npz_path} ({len(paths)} samples)")

    meta_path = out_dir / "inspect_meta.txt"
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"checkpoint: {ckpt_path.resolve()}\n")
        f.write(f"gradcam_target: image_backbone.layer4\n")
        f.write(f"image_embedding_dim: {img_emb.shape[1]}\n")
        f.write(f"spectra_embedding_dim: {spec_emb.shape[1]}\n")
        f.write(f"logits_dim: {logits_np.shape[1]}\n")
    print(f"Wrote {meta_path}")

    if args.gradcam_n > 0:
        save_gradcam_batch(
            model,
            val_paths,
            val_specs,
            val_labels,
            class_to_idx,
            idx_to_class,
            val_tf,
            device,
            out_dir,
            min(args.gradcam_n, len(val_paths)),
            args.seed + 1,
        )


if __name__ == "__main__":
    main()
