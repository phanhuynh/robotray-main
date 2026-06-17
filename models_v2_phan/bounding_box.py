import os
import cv2
import numpy as np
from tkinter import Tk, filedialog


# -----------------------
# UI
# -----------------------
def select_folder():
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="Select folder")
    root.destroy()
    return folder


def get_jpegs(folder):
    return [f for f in os.listdir(folder) if f.lower().endswith((".jpg",".jpeg"))]


def out_folder(folder):
    parent = os.path.dirname(folder)
    name = os.path.basename(folder)
    path = os.path.join(parent, name + "_bb")
    os.makedirs(path, exist_ok=True)
    return path


# -----------------------
# Preprocessing
# -----------------------
def preprocess(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5,5), 0)

    bg = cv2.blur(gray, (81,1))
    diff = cv2.absdiff(gray, bg)

    return gray, diff


# -----------------------
# MSER
# -----------------------
def mser_candidates(gray, diff):
    mser_params = [
        dict(delta=4, min_area=60, max_area=120000),
        dict(delta=5, min_area=120, max_area=120000),
        dict(delta=7, min_area=250, max_area=120000),
    ]

    candidates = []

    for src in [gray, diff]:
        for p in mser_params:
            mser = cv2.MSER_create(**p)
            regions,_ = mser.detectRegions(src)

            for pts in regions:
                x,y,w,h = cv2.boundingRect(np.array(pts))

                # SIZE FILTER (CRITICAL)
                if not (60 <= w <= 180 and 60 <= h <= 180):
                    continue

                candidates.append((x,y,w,h))

    return candidates


# -----------------------
# Expand box
# -----------------------
def expand_box(bbox, shape, scale=2.0):
    x,y,w,h = bbox
    cx = x + w//2
    cy = y + h//2

    nw = int(w * scale)
    nh = int(h * scale)

    x1 = max(0, cx - nw//2)
    y1 = max(0, cy - nh//2)
    x2 = min(shape[1], cx + nw//2)
    y2 = min(shape[0], cy + nh//2)

    return x1,y1,x2-x1,y2-y1


# -----------------------
# Local refine
# -----------------------
def refine(gray, bbox):
    x,y,w,h = bbox
    patch = gray[y:y+h, x:x+w]

    if patch.size == 0:
        return None

    bg = cv2.blur(patch, (41,1))
    diff = cv2.absdiff(patch, bg)

    _,mask = cv2.threshold(diff, 40,255,cv2.THRESH_BINARY)

    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7,7),np.uint8),2)

    contours,_ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    c = max(contours, key=cv2.contourArea)

    rx,ry,rw,rh = cv2.boundingRect(c)

    # final size filter again
    if not (60 <= rw <= 180 and 60 <= rh <= 180):
        return None

    return (x+rx, y+ry, rw, rh)


# -----------------------
# Draw
# -----------------------
def draw(img, bbox, color, label):
    out = img.copy()
    if bbox:
        x,y,w,h = bbox
        cv2.rectangle(out,(x,y),(x+w,y+h),color,2)
        cv2.putText(out,label,(x,y-5),cv2.FONT_HERSHEY_SIMPLEX,0.6,color,2)
    return out


# -----------------------
# Main
# -----------------------
def main():
    folder = select_folder()
    if not folder:
        return

    files = get_jpegs(folder)
    out = out_folder(folder)

    for f in files:
        img = cv2.imread(os.path.join(folder,f))

        gray, diff = preprocess(img)

        candidates = mser_candidates(gray, diff)

        best_multi = None
        best_refined = None

        for c in candidates[:10]:  # limit for speed
            expanded = expand_box(c, img.shape)

            refined = refine(gray, expanded)

            if refined:
                best_refined = refined
                break

        # fallback if no refine
        if candidates:
            best_multi = candidates[0]

        im1 = draw(img, best_multi, (0,255,255), "multi_mser")
        im2 = draw(img, best_refined, (255,255,0), "stripe_penalty")

        name,_ = os.path.splitext(f)
        cv2.imwrite(os.path.join(out, name+"_multi_mser.jpg"), im1)
        cv2.imwrite(os.path.join(out, name+"_stripe_penalty.jpg"), im2)

        print("done:", f)


if __name__ == "__main__":
    main()