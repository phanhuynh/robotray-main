# NOTE: Use conda environment "mineral_ml2" for this script.
# Interpreter: C:\Users\phuynh\AppData\Local\miniconda3\envs\mineral_ml2\python.exe
import os
import random
from pathlib import Path

import numpy as np
from PIL import Image
import matplotlib.pyplot as plt

from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, models

import csv

# =========================
# USER SETTINGS
# =========================
IMAGE_DIR = r"C:\Users\phuynh\Projects\robotray-main\robotray_v2\sample_outputs_v2"
MODEL_OUT = "mineral_classifier_resnet18.pth"
IMG_SIZE = 224
BATCH_SIZE = 32
EPOCHS = 8
LR = 1e-4
RANDOM_SEED = 42
NUM_WORKERS = 0                  # use 0 on Windows if you get DataLoader issues
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# If you want to force a specific set/order of classes, define them here.
# Otherwise they will be discovered automatically from filenames.
KNOWN_CLASSES = None
# Example:
# KNOWN_CLASSES = ["feldspar", "garnet", "rutile", "zircon"]


# =========================
# REPRODUCIBILITY
# =========================
def set_seed(seed: int = 42) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# =========================
# LABEL PARSING
# =========================
def extract_label_from_folder(folder_name: str) -> str:
    """
    Example:
    019262_2026_04_03_rutile_150 -> rutile
    018662_2026_04_02_monazite-bra_150 -> monazite-bra
    """
    parts = folder_name.split("_")
    if len(parts) < 2:
        raise ValueError(f"Unexpected folder name: {folder_name}")
    
    # label is second-to-last element
    # (because last is "150")
    return parts[-2].lower()
    return parts[-1].lower()


# =========================
# DATASET
# =========================
class MineralDataset(Dataset):
    def __init__(self, image_paths, labels, class_to_idx, transform=None):
        self.image_paths = image_paths
        self.labels = labels
        self.class_to_idx = class_to_idx
        self.transform = transform

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        img_path = self.image_paths[idx]
        label_str = self.labels[idx]
        label_idx = self.class_to_idx[label_str]

        image = Image.open(img_path).convert("RGB")

        if self.transform is not None:
            image = self.transform(image)

        return image, label_idx


# =========================
# FIND IMAGES
# =========================
def collect_images_and_labels(image_dir):
    image_dir = Path(image_dir)
    exts = {".jpg", ".jpeg"}

    image_paths = []
    labels = []

    # walk through all subfolders
    for subfolder in image_dir.iterdir():
        if not subfolder.is_dir():
            continue

        try:
            label = extract_label_from_folder(subfolder.name)
        except Exception as e:
            print(f"Skipping folder {subfolder.name}: {e}")
            continue

        for path in subfolder.iterdir():
            if path.is_file() and path.suffix.lower() in exts:
                image_paths.append(str(path))
                labels.append(label)

    if not image_paths:
        raise RuntimeError(f"No images found in {image_dir}")

    return image_paths, labels


# =========================
# TRAIN / EVAL
# =========================
def train_one_epoch(model, loader, criterion, optimizer, device):
    model.train()
    running_loss = 0.0
    correct = 0
    total = 0

    for images, targets in loader:
        images = images.to(device)
        targets = targets.to(device)

        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, targets)
        loss.backward()
        optimizer.step()

        running_loss += loss.item() * images.size(0)
        preds = outputs.argmax(dim=1)
        correct += (preds == targets).sum().item()
        total += targets.size(0)

    epoch_loss = running_loss / total
    epoch_acc = correct / total
    return epoch_loss, epoch_acc


@torch.no_grad()


@torch.no_grad()
def evaluate(model, loader, criterion, device, dataset=None, idx_to_class=None):
    model.eval()
    running_loss = 0.0
    correct = 0
    total = 0

    all_targets = []
    all_preds = []
    detailed_rows = []

    sample_index = 0

    for images, targets in loader:
        images = images.to(device)
        targets = targets.to(device)

        outputs = model(images)
        loss = criterion(outputs, targets)

        running_loss += loss.item() * images.size(0)

        probs = torch.softmax(outputs, dim=1)
        preds = outputs.argmax(dim=1)

        correct += (preds == targets).sum().item()
        total += targets.size(0)

        all_targets.extend(targets.cpu().numpy())
        all_preds.extend(preds.cpu().numpy())

        if dataset is not None and idx_to_class is not None:
            batch_size = images.size(0)

            for i in range(batch_size):
                ds_idx = sample_index + i

                image_path = dataset.image_paths[ds_idx]
                true_idx = int(targets[i].item())
                pred_idx = int(preds[i].item())
                pred_conf = float(probs[i, pred_idx].item())

                detailed_rows.append({
                    "image_path": image_path,
                    "true_idx": true_idx,
                    "true_class": idx_to_class[true_idx],
                    "pred_idx": pred_idx,
                    "pred_class": idx_to_class[pred_idx],
                    "pred_confidence": pred_conf,
                    "correct": int(pred_idx == true_idx),
                })

            sample_index += batch_size

    epoch_loss = running_loss / total
    epoch_acc = correct / total
    return epoch_loss, epoch_acc, all_targets, all_preds, detailed_rows



def plot_history(train_losses, val_losses, train_accs, val_accs):
    epochs = range(1, len(train_losses) + 1)

    plt.figure(figsize=(8, 5))
    plt.plot(epochs, train_losses, label="Train loss")
    plt.plot(epochs, val_losses, label="Val loss")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.title("Training and Validation Loss")
    plt.legend()
    plt.tight_layout()
    plt.savefig("loss_curve.png", dpi=150)
    plt.close()

    plt.figure(figsize=(8, 5))
    plt.plot(epochs, train_accs, label="Train accuracy")
    plt.plot(epochs, val_accs, label="Val accuracy")
    plt.xlabel("Epoch")
    plt.ylabel("Accuracy")
    plt.title("Training and Validation Accuracy")
    plt.legend()
    plt.tight_layout()
    plt.savefig("accuracy_curve.png", dpi=150)
    plt.close()


def split_by_folder(image_dir, test_size=0.2, seed=42):
    image_dir = Path(image_dir)
    subfolders = [f for f in image_dir.iterdir() if f.is_dir()]

    # extract label per folder
    folder_labels = [extract_label_from_folder(f.name) for f in subfolders]

    train_folders, val_folders = train_test_split(
        subfolders,
        test_size=test_size,
        random_state=seed,
        stratify=folder_labels
    )

    def gather(folders):
        paths, labels = [], []
        for f in folders:
            label = extract_label_from_folder(f.name)
            for p in f.iterdir():
                if p.suffix.lower() in [".jpg", ".jpeg"]:
                    paths.append(str(p))
                    labels.append(label)
        return paths, labels

    return gather(train_folders) + gather(val_folders)

# =========================
# MAIN
# =========================
def main():
    set_seed(RANDOM_SEED)

    print(f"Using device: {DEVICE}")

    image_paths, labels = collect_images_and_labels(IMAGE_DIR)

    unique_labels = sorted(set(labels)) if KNOWN_CLASSES is None else KNOWN_CLASSES
    class_to_idx = {cls_name: i for i, cls_name in enumerate(unique_labels)}
    idx_to_class = {i: cls_name for cls_name, i in class_to_idx.items()}

    print(f"Classes found: {unique_labels}")
    print(f"Total images: {len(image_paths)}")

    train_paths, train_labels, val_paths, val_labels = split_by_folder(IMAGE_DIR)

    print(f"Train images: {len(train_paths)}")
    print(f"Val images:   {len(val_paths)}")

    train_transform = transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(),
        transforms.RandomRotation(30),
        transforms.ColorJitter(brightness=0.1, contrast=0.1),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225]),
    ])

    val_transform = transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225]),
    ])

    train_dataset = MineralDataset(train_paths, train_labels, class_to_idx, transform=train_transform)
    val_dataset = MineralDataset(val_paths, val_labels, class_to_idx, transform=val_transform)

    train_loader = DataLoader(
        train_dataset,
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=NUM_WORKERS
    )

    val_loader = DataLoader(
        val_dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=NUM_WORKERS
    )

    # Pretrained ResNet18
    model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, len(unique_labels))
    model = model.to(DEVICE)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    best_val_acc = 0.0
    best_state = None

    train_losses, val_losses = [], []
    train_accs, val_accs = [], []

    for epoch in range(EPOCHS):
        train_loss, train_acc = train_one_epoch(model, train_loader, criterion, optimizer, DEVICE)
        # val_loss, val_acc, _, _ = evaluate(model, val_loader, criterion, DEVICE)
        val_loss, val_acc, _, _, _ = evaluate(
            model,
            val_loader,
            criterion,
            DEVICE,
            dataset=val_dataset,
            idx_to_class=idx_to_class
        )

        train_losses.append(train_loss)
        val_losses.append(val_loss)
        train_accs.append(train_acc)
        val_accs.append(val_acc)

        print(
            f"Epoch {epoch + 1}/{EPOCHS} | "
            f"Train loss: {train_loss:.4f} | Train acc: {train_acc:.4f} | "
            f"Val loss: {val_loss:.4f} | Val acc: {val_acc:.4f}"
        )

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = {
                "model_state_dict": model.state_dict(),
                "class_to_idx": class_to_idx,
                "idx_to_class": idx_to_class,
                "img_size": IMG_SIZE,
            }

    if best_state is not None:
        torch.save(best_state, MODEL_OUT)
        print(f"\nBest model saved to: {MODEL_OUT}")
        print(f"Best validation accuracy: {best_val_acc:.4f}")

    plot_history(train_losses, val_losses, train_accs, val_accs)
    print("Saved: loss_curve.png and accuracy_curve.png")

    # Final eval using best weights
    if best_state is not None:
        model.load_state_dict(best_state["model_state_dict"])

    # _, _, all_targets, all_preds = evaluate(model, val_loader, criterion, DEVICE)
    _, _, all_targets, all_preds, detailed_rows = evaluate(
    model,
    val_loader,
    criterion,
    DEVICE,
    dataset=val_dataset,
    idx_to_class=idx_to_class
)

    target_names = [idx_to_class[i] for i in range(len(idx_to_class))]

    print("\nClassification report:")
    print(classification_report(all_targets, all_preds, target_names=target_names, digits=4))

    print("Confusion matrix:")
    print(confusion_matrix(all_targets, all_preds))

    # Save all validation predictions
    all_csv = "val_predictions.csv"
    with open(all_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "image_path",
                "true_idx",
                "true_class",
                "pred_idx",
                "pred_class",
                "pred_confidence",
                "correct",
            ],
        )
        writer.writeheader()
        writer.writerows(detailed_rows)

    # Save wrong predictions only
    wrong_rows = [row for row in detailed_rows if row["correct"] == 0]
    wrong_csv = "wrong_predictions.csv"
    with open(wrong_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "image_path",
                "true_idx",
                "true_class",
                "pred_idx",
                "pred_class",
                "pred_confidence",
                "correct",
            ],
        )
        writer.writeheader()
        writer.writerows(wrong_rows)

    print(f"\nSaved all validation predictions to: {all_csv}")
    print(f"Saved wrong predictions to: {wrong_csv}")
    print(f"Number of wrong predictions: {len(wrong_rows)}")



if __name__ == "__main__":
    main()