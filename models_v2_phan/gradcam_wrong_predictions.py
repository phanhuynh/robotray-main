from pathlib import Path
import csv

import torch
import torch.nn as nn
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

from torchvision import transforms, models

from pytorch_grad_cam import GradCAM
from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget
from pytorch_grad_cam.utils.image import show_cam_on_image


MODEL_PATH = r"C:\Users\phuynh\Projects\robotray-main\models_v2_phan\mineral_classifier_resnet18.pth"
WRONG_CSV = r"C:\Users\phuynh\Projects\robotray-main\models_v2_phan\wrong_predictions.csv"
OUTPUT_DIR = r"C:\Users\phuynh\Projects\robotray-main\models_v2_phan\gradcam_wrong_predictions"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def load_model(model_path):
    checkpoint = torch.load(model_path, map_location=DEVICE, weights_only=False)

    idx_to_class = checkpoint["idx_to_class"]
    img_size = checkpoint["img_size"]

    model = models.resnet18(weights=None)
    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, len(idx_to_class))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(DEVICE)
    model.eval()

    return model, idx_to_class, img_size


def sanitize_filename(text: str) -> str:
    bad_chars = '<>:"/\\|?*'
    for ch in bad_chars:
        text = text.replace(ch, "_")
    return text


def main():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    model, idx_to_class, img_size = load_model(MODEL_PATH)

    transform = transforms.Compose([
        transforms.Resize((img_size, img_size)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225]
        )
    ])

    target_layers = [model.layer4[-1]]
    cam = GradCAM(model=model, target_layers=target_layers)

    with open(WRONG_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Found {len(rows)} wrong predictions.")

    for n, row in enumerate(rows, start=1):
        image_path = Path(row["image_path"])
        true_class = row["true_class"]
        pred_class = row["pred_class"]
        pred_conf = float(row["pred_confidence"])

        if not image_path.exists():
            print(f"[{n}/{len(rows)}] Missing file: {image_path}")
            continue

        image_pil = Image.open(image_path).convert("RGB")
        image_resized = image_pil.resize((img_size, img_size))
        image_np = np.array(image_resized).astype(np.float32) / 255.0

        input_tensor = transform(image_pil).unsqueeze(0).to(DEVICE)

        with torch.no_grad():
            outputs = model(input_tensor)
            probs = torch.softmax(outputs, dim=1)[0]
            pred_idx = int(torch.argmax(probs).item())

        targets = [ClassifierOutputTarget(pred_idx)]
        grayscale_cam = cam(input_tensor=input_tensor, targets=targets)[0]

        visualization = show_cam_on_image(
            image_np,
            grayscale_cam,
            use_rgb=True
        )

        fig = plt.figure(figsize=(12, 5))

        ax1 = fig.add_subplot(1, 2, 1)
        ax1.imshow(image_np)
        ax1.set_title("Original")
        ax1.axis("off")

        ax2 = fig.add_subplot(1, 2, 2)
        ax2.imshow(visualization)
        ax2.set_title(
            f"Grad-CAM\ntrue={true_class} | pred={pred_class} ({pred_conf:.3f})"
        )
        ax2.axis("off")

        fig.tight_layout()

        stem = sanitize_filename(image_path.stem)
        out_name = f"{n:03d}_true-{true_class}_pred-{pred_class}_{stem}.png"
        out_path = output_dir / out_name

        fig.savefig(out_path, dpi=150)
        plt.close(fig)

        print(f"[{n}/{len(rows)}] Saved: {out_path.name}")

    print(f"\nDone. Outputs saved in:\n{output_dir}")


if __name__ == "__main__":
    main()