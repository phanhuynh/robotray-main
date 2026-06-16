import random
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
import matplotlib.pyplot as plt
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms


# =========================
# USER SETTINGS
# =========================
IMAGE_DIR = r"C:\Users\phuynh\Projects\robotray-main\robotray_v2\sample_outputs_v2"
SPECTRA_CSV = r"C:\Users\phuynh\Projects\robotray-main\models_phan\df_snr_elem.csv"
MODEL_OUT = "mineral_fusion_resnet18_spectra.pth"
LOSS_CURVE_OUT = "loss_curve_fuse.png"
ACCURACY_CURVE_OUT = "accuracy_curve_fuse.png"

IMG_SIZE = 224
BATCH_SIZE = 32
EPOCHS = 10
LR = 1e-4
RANDOM_SEED = 42
NUM_WORKERS = 0
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def set_seed(seed: int = 42) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def parse_image_filename(path: Path):
    # Example: 017762_2026_04_01_rutile.jpg
    parts = path.stem.split("_")
    if len(parts) < 5:
        raise ValueError(f"Unexpected image filename format: {path.name}")
    image_id = parts[0]
    date_str = "_".join(parts[1:4])
    label = "_".join(parts[4:]).lower()
    sample_key = f"{image_id}_{date_str}_{label}"
    return sample_key, label


def collect_images_by_key(image_dir: str):
    image_dir = Path(image_dir)
    exts = {".jpg", ".jpeg", ".png"}

    key_to_images = {}
    key_to_label = {}

    for p in image_dir.rglob("*"):
        if not (p.is_file() and p.suffix.lower() in exts):
            continue
        try:
            sample_key, label = parse_image_filename(p)
        except Exception as e:
            print(f"Skipping image {p.name}: {e}")
            continue

        if sample_key in key_to_label and key_to_label[sample_key] != label:
            print(f"Warning: conflicting image labels for key {sample_key}; keeping first.")
            continue

        key_to_images.setdefault(sample_key, []).append(str(p))
        key_to_label[sample_key] = label

    if not key_to_images:
        raise RuntimeError(f"No usable images found in {image_dir}")
    return key_to_images, key_to_label


def parse_spectra_test_key(test_value: str) -> str:
    # Example: 017762_2026_04_01_rutile_150_017762 -> 017762_2026_04_01_rutile
    test_value = str(test_value).strip()
    parts = test_value.split("_")
    if len(parts) < 7:
        raise ValueError(f"Unexpected test value format: {test_value}")
    image_id = parts[-1]
    date_str = "_".join(parts[1:4])
    label = parts[-3].lower()
    return f"{image_id}_{date_str}_{label}"


def build_spectra_map(csv_path: str):
    df = pd.read_csv(csv_path)
    required_cols = {"test", "target"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in spectra csv: {missing}")

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    spectra_cols = [c for c in numeric_cols if c not in ("voltage",)]
    if not spectra_cols:
        raise ValueError("No numeric spectra feature columns found.")

    # Narrow working frame: avoid inserting new columns into the huge read_csv frame (pandas PerformanceWarning).
    meta = pd.DataFrame(
        {
            "sample_key": df["test"].astype(str).map(parse_spectra_test_key),
            "target": df["target"].astype(str).str.lower(),
            "voltage": df["voltage"].astype(str).str.lower(),
        }
    )
    work = pd.concat([meta, df[spectra_cols].reset_index(drop=True)], axis=1)

    voltage_order = [
        "mininghighvoltage",
        "mininglowvoltage",
        "soilhighvoltage",
        "soilmidvoltage",
        "soillowvoltage",
    ]
    grouped = work.groupby("sample_key", sort=False)
    key_to_spectra = {}
    key_to_target = {}
    bad_keys = []
    bad_voltage_keys = []

    for sample_key, g in grouped:
        if len(g) != 5:
            bad_keys.append(sample_key)
            continue
        g = g.drop_duplicates(subset=["voltage"], keep="first")
        if len(g) != 5 or set(g["voltage"]) != set(voltage_order):
            bad_voltage_keys.append(sample_key)
            continue

        g = g.set_index("voltage").loc[voltage_order]
        key_to_spectra[sample_key] = g[spectra_cols].to_numpy(dtype=np.float32).reshape(-1)
        key_to_target[sample_key] = g["target"].mode(dropna=True).iat[0]

    if bad_keys:
        print(f"Warning: {len(bad_keys)} sample keys did not have exactly 5 spectra rows and were skipped.")
    if bad_voltage_keys:
        print(f"Warning: {len(bad_voltage_keys)} sample keys had invalid voltage composition and were skipped.")

    return key_to_spectra, key_to_target, spectra_cols, voltage_order


class FusionDataset(Dataset):
    def __init__(self, image_paths, spectra, labels, class_to_idx, transform=None):
        self.image_paths = image_paths
        self.spectra = spectra.astype(np.float32)
        self.labels = labels
        self.class_to_idx = class_to_idx
        self.transform = transform

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        image = Image.open(self.image_paths[idx]).convert("RGB")
        if self.transform is not None:
            image = self.transform(image)

        spec = torch.from_numpy(self.spectra[idx])
        label_idx = self.class_to_idx[self.labels[idx]]
        return image, spec, label_idx


class EarlyFusionNet(nn.Module):
    def __init__(self, num_classes: int, spectra_dim: int):
        super().__init__()
        backbone = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
        in_features = backbone.fc.in_features
        backbone.fc = nn.Identity()
        self.image_backbone = backbone

        self.spectra_mlp = nn.Sequential(
            nn.Linear(spectra_dim, 256),
            nn.BatchNorm1d(256),
            nn.ReLU(inplace=True),
            nn.Dropout(0.2),
            nn.Linear(256, 128),
            nn.ReLU(inplace=True),
        )

        self.classifier = nn.Sequential(
            nn.Linear(in_features + 128, 256),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(256, num_classes),
        )

    def forward(self, images, spectra):
        img_feat = self.image_backbone(images)
        spec_feat = self.spectra_mlp(spectra)
        fused = torch.cat([img_feat, spec_feat], dim=1)
        return self.classifier(fused)


def train_one_epoch(model, loader, criterion, optimizer, device):
    model.train()
    running_loss = 0.0
    correct = 0
    total = 0

    for images, spectra, targets in loader:
        images = images.to(device)
        spectra = spectra.to(device)
        targets = targets.to(device)

        optimizer.zero_grad()
        outputs = model(images, spectra)
        loss = criterion(outputs, targets)
        loss.backward()
        optimizer.step()

        running_loss += loss.item() * images.size(0)
        preds = outputs.argmax(dim=1)
        correct += (preds == targets).sum().item()
        total += targets.size(0)

    return running_loss / total, correct / total


@torch.no_grad()
def evaluate(model, loader, criterion, device):
    model.eval()
    running_loss = 0.0
    correct = 0
    total = 0
    all_targets = []
    all_preds = []

    for images, spectra, targets in loader:
        images = images.to(device)
        spectra = spectra.to(device)
        targets = targets.to(device)

        outputs = model(images, spectra)
        loss = criterion(outputs, targets)

        running_loss += loss.item() * images.size(0)
        preds = outputs.argmax(dim=1)
        correct += (preds == targets).sum().item()
        total += targets.size(0)

        all_targets.extend(targets.cpu().numpy())
        all_preds.extend(preds.cpu().numpy())

    return running_loss / total, correct / total, all_targets, all_preds


def make_examples_from_keys(keys, key_to_images, key_to_label, key_to_spectra):
    image_paths, labels, spectra_rows = [], [], []
    missing_spectra_keys = []

    for sample_key in keys:
        if sample_key not in key_to_spectra:
            missing_spectra_keys.append(sample_key)
            continue
        spec_vec = key_to_spectra[sample_key]
        for img_path in key_to_images[sample_key]:
            image_paths.append(img_path)
            labels.append(key_to_label[sample_key])
            spectra_rows.append(spec_vec)

    if missing_spectra_keys:
        print(f"Warning: {len(missing_spectra_keys)} sample keys have images but no spectra.")

    if not image_paths:
        raise RuntimeError("No paired (image + spectra) samples were created.")

    spectra_arr = np.vstack(spectra_rows).astype(np.float32)
    return image_paths, labels, spectra_arr


def plot_history(train_losses, val_losses, train_accs, val_accs):
    epochs = range(1, len(train_losses) + 1)

    plt.figure(figsize=(8, 5))
    plt.plot(epochs, train_losses, label="Train loss")
    plt.plot(epochs, val_losses, label="Val loss")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.title("Fusion Training and Validation Loss")
    plt.legend()
    plt.tight_layout()
    plt.savefig(LOSS_CURVE_OUT, dpi=150)
    plt.close()

    plt.figure(figsize=(8, 5))
    plt.plot(epochs, train_accs, label="Train accuracy")
    plt.plot(epochs, val_accs, label="Val accuracy")
    plt.xlabel("Epoch")
    plt.ylabel("Accuracy")
    plt.title("Fusion Training and Validation Accuracy")
    plt.legend()
    plt.tight_layout()
    plt.savefig(ACCURACY_CURVE_OUT, dpi=150)
    plt.close()


def main():
    set_seed(RANDOM_SEED)
    print(f"Using device: {DEVICE}")

    key_to_images, key_to_label = collect_images_by_key(IMAGE_DIR)
    key_to_spectra, key_to_target, spectra_cols, voltage_order = build_spectra_map(SPECTRA_CSV)

    common_keys = sorted(set(key_to_images).intersection(key_to_spectra))
    if not common_keys:
        raise RuntimeError("No overlapping sample keys between image names and spectra csv.")

    # Keep only keys where image-derived label agrees with spectra target.
    valid_keys = []
    mismatched = []
    for k in common_keys:
        img_label = key_to_label[k]
        spec_label = key_to_target[k]
        if img_label == spec_label:
            valid_keys.append(k)
        else:
            mismatched.append((k, img_label, spec_label))

    if mismatched:
        print(f"Warning: {len(mismatched)} sample-key label mismatches found and skipped.")
        for row in mismatched[:5]:
            print("  mismatch:", row)

    if len(valid_keys) < 2:
        raise RuntimeError("Too few valid sample keys after matching labels.")

    key_labels = [key_to_label[k] for k in valid_keys]
    train_keys, val_keys = train_test_split(
        valid_keys,
        test_size=0.2,
        random_state=RANDOM_SEED,
        stratify=key_labels,
    )

    train_paths, train_labels, train_specs = make_examples_from_keys(
        train_keys, key_to_images, key_to_label, key_to_spectra
    )
    val_paths, val_labels, val_specs = make_examples_from_keys(
        val_keys, key_to_images, key_to_label, key_to_spectra
    )

    classes = sorted(set(train_labels) | set(val_labels))
    class_to_idx = {c: i for i, c in enumerate(classes)}
    idx_to_class = {i: c for c, i in class_to_idx.items()}

    scaler = StandardScaler()
    train_specs = scaler.fit_transform(train_specs).astype(np.float32)
    val_specs = scaler.transform(val_specs).astype(np.float32)

    train_tf = transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(),
        transforms.RandomRotation(30),
        transforms.ColorJitter(brightness=0.1, contrast=0.1),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    val_tf = transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    train_ds = FusionDataset(train_paths, train_specs, train_labels, class_to_idx, transform=train_tf)
    val_ds = FusionDataset(val_paths, val_specs, val_labels, class_to_idx, transform=val_tf)

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=NUM_WORKERS)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS)

    print(f"Classes: {classes}")
    print(f"Train samples: {len(train_ds)} | Val samples: {len(val_ds)}")
    print(f"Spectra dimension: {train_specs.shape[1]}")

    model = EarlyFusionNet(num_classes=len(classes), spectra_dim=train_specs.shape[1]).to(DEVICE)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    best_val_acc = 0.0
    best_state = None
    train_losses, val_losses = [], []
    train_accs, val_accs = [], []

    for epoch in range(EPOCHS):
        tr_loss, tr_acc = train_one_epoch(model, train_loader, criterion, optimizer, DEVICE)
        va_loss, va_acc, _, _ = evaluate(model, val_loader, criterion, DEVICE)
        train_losses.append(tr_loss)
        val_losses.append(va_loss)
        train_accs.append(tr_acc)
        val_accs.append(va_acc)
        print(
            f"Epoch {epoch + 1}/{EPOCHS} | "
            f"Train loss {tr_loss:.4f} acc {tr_acc:.4f} | "
            f"Val loss {va_loss:.4f} acc {va_acc:.4f}"
        )

        if va_acc > best_val_acc:
            best_val_acc = va_acc
            best_state = {
                "model_state_dict": model.state_dict(),
                "class_to_idx": class_to_idx,
                "idx_to_class": idx_to_class,
                "img_size": IMG_SIZE,
                "spectra_columns": spectra_cols,
                "spectra_voltage_order": voltage_order,
                "scaler_mean": scaler.mean_.astype(np.float32),
                "scaler_scale": scaler.scale_.astype(np.float32),
            }

    if best_state is None:
        raise RuntimeError("Training did not produce a best checkpoint.")

    torch.save(best_state, MODEL_OUT)
    print(f"Best model saved to: {MODEL_OUT}")
    print(f"Best validation accuracy: {best_val_acc:.4f}")
    plot_history(train_losses, val_losses, train_accs, val_accs)
    print(f"Saved curves: {LOSS_CURVE_OUT}, {ACCURACY_CURVE_OUT}")

    model.load_state_dict(best_state["model_state_dict"])
    _, _, all_targets, all_preds = evaluate(model, val_loader, criterion, DEVICE)

    target_names = [idx_to_class[i] for i in range(len(idx_to_class))]
    print("\nClassification report:")
    print(classification_report(all_targets, all_preds, target_names=target_names, digits=4))
    print("Confusion matrix:")
    print(confusion_matrix(all_targets, all_preds))


if __name__ == "__main__":
    main()
