import os
import re
from pathlib import Path
import cv2
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from tkinter import Tk, filedialog


# =========================
# Settings
# =========================
N_ROWS = 15
N_COLS = 10
N_CELLS = N_ROWS * N_COLS  # 150
VALID_EXTS = {".jpg", ".jpeg", ".JPG", ".JPEG"}


# =========================
# Folder picker
# =========================
def choose_folder():
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="Select folder containing JPEG files")
    root.destroy()
    return folder


# =========================
# Test number helpers
# =========================
def extract_first_6_digits(text):
    m = re.match(r"(\d{6})", text)
    return int(m.group(1)) if m else None


def get_start_test_from_folder(folder_path):
    folder_name = Path(folder_path).name
    start_test = extract_first_6_digits(folder_name)
    if start_test is None:
        raise ValueError(
            f"Folder name must start with 6 digits. Got: {folder_name}"
        )
    return start_test


def build_expected_test_numbers(start_test):
    return [start_test + i for i in range(N_CELLS)]


def find_files_by_test_number(folder_path):
    """
    Returns dict:
        {test_number: Path_to_file}
    using the first 6 digits of each filename.
    If duplicates exist, the first one in sorted order is kept.
    """
    folder = Path(folder_path)
    files = sorted(
        [p for p in folder.iterdir() if p.is_file() and p.suffix in VALID_EXTS]
    )

    mapping = {}
    for p in files:
        test_num = extract_first_6_digits(p.name)
        if test_num is not None and test_num not in mapping:
            mapping[test_num] = p
    return mapping


# =========================
# Grid layout (same pattern as screenshot)
# =========================
def serpentine_position(index_0_based):
    """
    index_0_based: 0..149
    Returns (row, col) in a 15 x 10 serpentine layout.

    Col 0: top->bottom
    Col 1: bottom->top
    Col 2: top->bottom
    ...
    """
    col = index_0_based // N_ROWS
    pos_in_col = index_0_based % N_ROWS

    if col % 2 == 0:
        row = pos_in_col
    else:
        row = N_ROWS - 1 - pos_in_col

    return row, col


def build_test_number_grid(start_test):
    grid = np.zeros((N_ROWS, N_COLS), dtype=int)
    for i in range(N_CELLS):
        row, col = serpentine_position(i)
        grid[row, col] = start_test + i
    return grid


# =========================
# Bounding box detection
# =========================
def detect_colored_bbox(image_bgr):
    """
    Detects a yellow or green rectangle.
    Returns bbox as (x, y, w, h).
    """
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    # Yellow mask
    yellow_lower = np.array([15, 80, 80], dtype=np.uint8)
    yellow_upper = np.array([45, 255, 255], dtype=np.uint8)
    mask_yellow = cv2.inRange(hsv, yellow_lower, yellow_upper)

    # Green mask
    green_lower = np.array([35, 50, 50], dtype=np.uint8)
    green_upper = np.array([95, 255, 255], dtype=np.uint8)
    mask_green = cv2.inRange(hsv, green_lower, green_upper)

    mask = cv2.bitwise_or(mask_yellow, mask_green)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.dilate(mask, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        raise ValueError("No yellow/green box detected.")

    best = None
    best_score = -1

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        area = w * h

        if area < 200:
            continue

        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.03 * peri, True)

        rect_like_bonus = 100000 if len(approx) == 4 else 0
        aspect = h / max(w, 1)

        # Favor reasonably large, rectangle-like, taller boxes
        score = area + rect_like_bonus + 1000 * aspect

        if score > best_score:
            best_score = score
            best = (x, y, w, h)

    if best is None:
        raise ValueError("No suitable bounding box found.")

    return best


# =========================
# Metrics
# =========================
def compute_blur(image_bgr, bbox):
    x, y, w, h = bbox
    crop = image_bgr[y:y + h, x:x + w]
    if crop.size == 0:
        raise ValueError("Empty crop for blur calculation.")
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    return float(blur_score)


def compute_center_distance_normalized(image_bgr, bbox):
    H, W = image_bgr.shape[:2]
    x, y, w, h = bbox

    img_cx = W / 2.0
    img_cy = H / 2.0
    box_cx = x + w / 2.0
    box_cy = y + h / 2.0

    raw_dist = np.sqrt((box_cx - img_cx) ** 2 + (box_cy - img_cy) ** 2)
    max_dist = np.sqrt((W / 2.0) ** 2 + (H / 2.0) ** 2)

    return float(raw_dist / max_dist)


def score_image(image_path):
    image_bgr = cv2.imread(str(image_path))
    if image_bgr is None:
        raise ValueError(f"Could not read image: {image_path}")

    bbox = detect_colored_bbox(image_bgr)
    blur = compute_blur(image_bgr, bbox)
    dist = compute_center_distance_normalized(image_bgr, bbox)

    return {
        "blur": blur,
        "distance": dist,
        "bbox": bbox,
    }


# =========================
# Plotting
# =========================
def draw_metric_grid(metric_grid, test_num_grid, title, output_path, cmap_name="viridis"):
    """
    metric_grid: float array shape (15, 10), np.nan allowed
    test_num_grid: int array shape (15, 10)
    """
    fig, ax = plt.subplots(figsize=(10, 12))

    data = np.ma.masked_invalid(metric_grid)
    cmap = plt.get_cmap(cmap_name).copy()
    cmap.set_bad(color="lightgray")

    # Auto-normalize on valid cells only
    valid = metric_grid[np.isfinite(metric_grid)]
    if len(valid) == 0:
        norm = Normalize(vmin=0, vmax=1)
    else:
        vmin = np.min(valid)
        vmax = np.max(valid)
        if vmin == vmax:
            vmax = vmin + 1e-9
        norm = Normalize(vmin=vmin, vmax=vmax)

    im = ax.imshow(data, cmap=cmap, norm=norm, origin="upper")

    # Grid lines
    ax.set_xticks(np.arange(-0.5, N_COLS, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, N_ROWS, 1), minor=True)
    ax.grid(which="minor", color="black", linestyle="-", linewidth=1)
    ax.tick_params(which="minor", bottom=False, left=False)

    # Hide axis labels
    ax.set_xticks([])
    ax.set_yticks([])

    # Annotate each square with its test number
    for r in range(N_ROWS):
        for c in range(N_COLS):
            txt = str(test_num_grid[r, c])

            # choose text color based on cell brightness when valid
            if np.isfinite(metric_grid[r, c]):
                rgba = cmap(norm(metric_grid[r, c]))
                brightness = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
                txt_color = "black" if brightness > 0.6 else "white"
            else:
                txt_color = "black"

            ax.text(
                c, r, txt,
                ha="center", va="center",
                fontsize=9, color=txt_color
            )

    ax.set_title(title, fontsize=14, pad=14)
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.ax.set_ylabel(title, rotation=90)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# =========================
# Main
# =========================
def main():
    folder = choose_folder()
    if not folder:
        print("No folder selected.")
        return

    folder = Path(folder)
    start_test = get_start_test_from_folder(folder)
    test_num_grid = build_test_number_grid(start_test)
    file_map = find_files_by_test_number(folder)

    blur_grid = np.full((N_ROWS, N_COLS), np.nan, dtype=float)
    dist_grid = np.full((N_ROWS, N_COLS), np.nan, dtype=float)

    expected_tests = build_expected_test_numbers(start_test)

    results_lines = []
    results_lines.append("test_number,filename,blur,distance_from_center_normalized,bbox_x,bbox_y,bbox_w,bbox_h,status")

    for idx, test_num in enumerate(expected_tests):
        row, col = serpentine_position(idx)

        if test_num not in file_map:
            results_lines.append(f"{test_num},,nan,nan,,,,,missing_file")
            continue

        image_path = file_map[test_num]

        try:
            result = score_image(image_path)
            blur_grid[row, col] = result["blur"]
            dist_grid[row, col] = result["distance"]
            x, y, w, h = result["bbox"]

            results_lines.append(
                f"{test_num},{image_path.name},{result['blur']},{result['distance']},{x},{y},{w},{h},ok"
            )
            print(f"Processed {image_path.name}")
        except Exception as e:
            results_lines.append(f"{test_num},{image_path.name},nan,nan,,,,,error:{str(e).replace(',', ';')}")
            print(f"Error on {image_path.name}: {e}")

    # Save plots
    blur_plot_path = folder / "blur_grid.png"
    dist_plot_path = folder / "distance_from_center_grid.png"

    draw_metric_grid(
        metric_grid=blur_grid,
        test_num_grid=test_num_grid,
        title="Blur",
        output_path=blur_plot_path,
        cmap_name="viridis"
    )

    draw_metric_grid(
        metric_grid=dist_grid,
        test_num_grid=test_num_grid,
        title="Distance from center",
        output_path=dist_plot_path,
        cmap_name="viridis"
    )

    # Save CSV
    csv_path = folder / "image_scores.csv"
    csv_path.write_text("\n".join(results_lines), encoding="utf-8")

    print("\nDone.")
    print(f"Saved:\n- {blur_plot_path}\n- {dist_plot_path}\n- {csv_path}")


if __name__ == "__main__":
    main()