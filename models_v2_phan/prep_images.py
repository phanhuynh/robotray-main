import os
import random
import shutil
from pathlib import Path

# -----------------------------
# SETTINGS
# -----------------------------
PROJECT_ROOT = Path(r"C:\Users\phuynh\Projects\robotray-main\models_v2_phan")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}
TRAIN_RATIO = 0.8
SEED = 42

IMAGES_ALL = PROJECT_ROOT / "dataset" / "images" / "all"
LABELS_ALL = PROJECT_ROOT / "dataset" / "labels" / "all"

IMAGES_TRAIN = PROJECT_ROOT / "dataset" / "images" / "train"
IMAGES_VAL = PROJECT_ROOT / "dataset" / "images" / "val"
LABELS_TRAIN = PROJECT_ROOT / "dataset" / "labels" / "train"
LABELS_VAL = PROJECT_ROOT / "dataset" / "labels" / "val"

DATA_YAML = PROJECT_ROOT / "dataset" / "data.yaml"
ALLOW_MISSING_LABELS = True


def reset_folder(folder: Path) -> None:
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)


def collect_images(images_folder: Path):
    return sorted([
        p for p in images_folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ])


def copy_pair(image_path: Path, src_labels: Path, dst_images: Path, dst_labels: Path) -> bool:
    label_path = src_labels / f"{image_path.stem}.txt"
    shutil.copy2(image_path, dst_images / image_path.name)

    if label_path.exists():
        shutil.copy2(label_path, dst_labels / label_path.name)
        return True

    if not ALLOW_MISSING_LABELS:
        raise FileNotFoundError(f"Missing label file for image: {image_path.name}")

    # Empty YOLO label file means "no objects in this image".
    (dst_labels / f"{image_path.stem}.txt").write_text("", encoding="utf-8")
    return False


def main():
    if not IMAGES_ALL.exists():
        raise FileNotFoundError(f"Images folder not found: {IMAGES_ALL}")
    if not LABELS_ALL.exists():
        raise FileNotFoundError(f"Labels folder not found: {LABELS_ALL}")

    images = collect_images(IMAGES_ALL)
    if not images:
        raise RuntimeError(f"No images found in: {IMAGES_ALL}")

    random.seed(SEED)
    random.shuffle(images)

    n_train = max(1, int(len(images) * TRAIN_RATIO))
    train_images = images[:n_train]
    val_images = images[n_train:]

    if not val_images:
        raise RuntimeError("Validation set is empty. Add more images.")

    # Reset output folders
    reset_folder(IMAGES_TRAIN)
    reset_folder(IMAGES_VAL)
    reset_folder(LABELS_TRAIN)
    reset_folder(LABELS_VAL)

    # Copy files
    missing_labels = []
    for img in train_images:
        has_label = copy_pair(img, LABELS_ALL, IMAGES_TRAIN, LABELS_TRAIN)
        if not has_label:
            missing_labels.append(img.name)

    for img in val_images:
        has_label = copy_pair(img, LABELS_ALL, IMAGES_VAL, LABELS_VAL)
        if not has_label:
            missing_labels.append(img.name)

    # Write YAML
    yaml_text = f"""path: {str((PROJECT_ROOT / "dataset").resolve()).replace("\\\\", "/")}
train: images/train
val: images/val

names:
  0: mineral
"""
    DATA_YAML.write_text(yaml_text, encoding="utf-8")

    print("Done.")
    print(f"Total images: {len(images)}")
    print(f"Train images: {len(train_images)}")
    print(f"Val images:   {len(val_images)}")
    print(f"YAML saved to: {DATA_YAML}")
    if missing_labels:
        print(f"Warning: created empty labels for {len(missing_labels)} image(s).")
        print("To use real boxes, add matching .txt files in labels/all.")


if __name__ == "__main__":
    main()