import os
import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import cv2
import numpy as np


# ============================================================
# CONFIG
# ============================================================

VALID_EXTS = {".jpg", ".jpeg", ".JPG", ".JPEG"}

# Skip files that already look like outputs
SKIP_DERIVED_OUTPUTS = True

# Output file suffix
SUFFIX_CLEAN = "_vlines"

# JPEG save quality
JPEG_QUALITY = 95


# ============================================================
# FILE / FOLDER HELPERS
# ============================================================

def choose_input_folder():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="Select folder containing JPEG files")
    root.destroy()
    return folder


def natural_key(s):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r"(\d+)", str(s))]


def is_valid_jpeg(path: Path) -> bool:
    return path.suffix in VALID_EXTS


def is_derived_output(name: str) -> bool:
    lname = name.lower()
    derived_markers = [
        "_bbox", "_boxed", "_preview", "_mask",
        "_stripe_removed", "_stripe_preview", "_stripe_mask", "_stripe_bbox",
        "_vlines"
    ]
    return any(marker in lname for marker in derived_markers)


def get_jpeg_files(folder):
    paths = [p for p in Path(folder).iterdir() if p.is_file() and is_valid_jpeg(p)]
    if SKIP_DERIVED_OUTPUTS:
        paths = [p for p in paths if not is_derived_output(p.stem)]
    return sorted(paths, key=lambda p: natural_key(p.name))


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


# ============================================================
# IMAGE PROCESSING
# ============================================================

def build_output_folder(input_folder):
    base_name = os.path.basename(os.path.normpath(input_folder))
    parent_dir = os.path.dirname(os.path.normpath(input_folder))
    return os.path.join(parent_dir, f"{base_name}_vlines")


def suppress_vertical_lines_on_luma(L):
    """
    Remove / reduce vertical stripe background while preserving compact objects.

    Main idea:
    1) Normalize broad column-to-column brightness variation
    2) Explicitly estimate tall vertical structures with morphology
    3) Subtract those vertical structures
    4) Light cleanup
    """
    Lf = L.astype(np.float32)
    h, w = L.shape

    # --------------------------------------------------------
    # Step 1: broad column normalization
    # --------------------------------------------------------
    col_profile = np.median(Lf, axis=0)

    # Very broad smoothing across columns to estimate low-frequency banding
    k = max(31, (w // 10) | 1)
    smooth_profile = cv2.GaussianBlur(col_profile.reshape(1, -1), (k, 1), 0).reshape(-1)
    smooth_profile = np.clip(smooth_profile, 1.0, None)

    target = np.median(smooth_profile)
    gain = target / smooth_profile
    gain = np.clip(gain, 0.7, 1.5)

    norm = Lf * gain[np.newaxis, :]
    norm = np.clip(norm, 0, 255).astype(np.uint8)

    # --------------------------------------------------------
    # Step 2: estimate vertical structures explicitly
    # --------------------------------------------------------
    # Morphological opening with a tall thin kernel keeps vertical lines
    
    # vertical_kernel_height = max(21, h // 18)
    vertical_kernel_height = 160

    if vertical_kernel_height % 2 == 0:
        vertical_kernel_height += 1

    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, vertical_kernel_height)
    )
    vertical_struct = cv2.morphologyEx(norm, cv2.MORPH_OPEN, vertical_kernel)

    # Slight horizontal blur on the extracted vertical component
    # to make subtraction less harsh / less stripy
    vertical_struct = cv2.GaussianBlur(vertical_struct, (9, 1), 0)

    # --------------------------------------------------------
    # Step 3: subtract vertical structures
    # --------------------------------------------------------
    reduced = cv2.subtract(norm, vertical_struct)

    # --------------------------------------------------------
    # Step 4: mild cleanup
    # --------------------------------------------------------
    # Small horizontal smoothing to reduce residual stripe texture
    reduced = cv2.GaussianBlur(reduced, (7, 3), 0)

    return reduced


def fix_vertical_background(img_bgr):
    """
    Process image in LAB space so we mainly alter brightness, not color.
    """
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    L, A, B = cv2.split(lab)

    L_clean = suppress_vertical_lines_on_luma(L)

    lab_clean = cv2.merge([L_clean, A, B])
    clean_bgr = cv2.cvtColor(lab_clean, cv2.COLOR_LAB2BGR)

    return clean_bgr


# ============================================================
# MAIN PROCESSING
# ============================================================

def process_one_image(img_path, output_dir):
    img = cv2.imread(str(img_path))
    if img is None:
        print(f"[WARN] Could not read: {img_path.name}")
        return

    clean_bgr = fix_vertical_background(img)

    out_name = f"{img_path.stem}{SUFFIX_CLEAN}.jpg"
    out_path = os.path.join(output_dir, out_name)

    ok = cv2.imwrite(out_path, clean_bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if ok:
        print(f"[OK] {img_path.name} -> {out_name}")
    else:
        print(f"[WARN] Failed to save: {out_name}")


def main():
    input_folder = choose_input_folder()
    if not input_folder:
        print("No folder selected.")
        return

    jpeg_files = get_jpeg_files(input_folder)
    if not jpeg_files:
        print("No JPEG files found.")
        return

    output_dir = build_output_folder(input_folder)
    ensure_dir(output_dir)

    print(f"Input folder : {input_folder}")
    print(f"Output folder: {output_dir}")
    print(f"Found {len(jpeg_files)} JPEG files\n")

    for img_path in jpeg_files:
        try:
            process_one_image(img_path, output_dir)
        except Exception as e:
            print(f"[ERROR] {img_path.name}: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()