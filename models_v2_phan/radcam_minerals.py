from pathlib import Path
import torch
import torch.nn as nn
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

from torchvision import transforms, models

from pytorch_grad_cam import GradCAM
from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget
from pytorch_grad_cam.utils.image import show_cam_on_image


# =========================
# USER SETTINGS
# =========================
MODEL_PATH = r"C:\Users\phuynh\Projects\robotray-main\models_v2_phan\mineral_classifier_resnet18.pth"

# Pick ONE folder (it will auto-select an image inside)
IMAGE_FOLDER = r"C:\Users\phuynh\Projects\robotray-main\robotray_v2\sample_outputs_v2\020462_2026_04_07_feldspar_150"

OUTPUT_PATH = "gradcam_result.png"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# =========================
# LOAD MODEL
# =========================
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


# =========================
# GET IMAGE
# =========================
def get_image_from_folder(folder_path):
    folder = Path(folder_path)

    image_files = sorted([
        p for p in folder.iterdir()
        if p.suffix.lower() in [".jpg", ".jpeg"]
    ])

    if not image_files:
        raise RuntimeError(f"No images found in {folder_path}")

    image_path = image_files[0]  # pick first image
    print(f"Using image: {image_path.name}")

    return image_path


# =========================
# MAIN
# =========================
def main():
    model, idx_to_class, img_size = load_model(MODEL_PATH)

    image_path = get_image_from_folder(IMAGE_FOLDER)

    # Load image
    image_pil = Image.open(image_path).convert("RGB")
    image_resized = image_pil.resize((img_size, img_size))

    image_np = np.array(image_resized).astype(np.float32) / 255.0

    transform = transforms.Compose([
        transforms.Resize((img_size, img_size)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225]
        )
    ])

    input_tensor = transform(image_pil).unsqueeze(0).to(DEVICE)

    # Prediction
    with torch.no_grad():
        outputs = model(input_tensor)
        probs = torch.softmax(outputs, dim=1)[0]

        pred_idx = int(torch.argmax(probs))
        pred_class = idx_to_class[pred_idx]
        pred_prob = float(probs[pred_idx])

    print(f"\nPrediction: {pred_class} ({pred_prob:.4f})")

    # =========================
    # GRAD-CAM
    # =========================
    target_layers = [model.layer4[-1]]

    cam = GradCAM(model=model, target_layers=target_layers)

    targets = [ClassifierOutputTarget(pred_idx)]

    grayscale_cam = cam(input_tensor=input_tensor, targets=targets)[0]

    visualization = show_cam_on_image(
        image_np,
        grayscale_cam,
        use_rgb=True
    )

    # =========================
    # DISPLAY
    # =========================
    plt.figure(figsize=(12, 5))

    plt.subplot(1, 2, 1)
    plt.imshow(image_np)
    plt.title("Original")
    plt.axis("off")

    plt.subplot(1, 2, 2)
    plt.imshow(visualization)
    plt.title(f"Grad-CAM\n{pred_class} ({pred_prob:.3f})")
    plt.axis("off")

    plt.tight_layout()
    plt.savefig(OUTPUT_PATH, dpi=150)
    plt.show()

    print(f"\nSaved Grad-CAM to: {OUTPUT_PATH}")

    print("\nClass probabilities:")
    for i in range(len(idx_to_class)):
        print(f"  {idx_to_class[i]}: {probs[i].item():.4f}")


# =========================
if __name__ == "__main__":
    main()