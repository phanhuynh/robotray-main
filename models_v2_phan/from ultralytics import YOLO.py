from ultralytics import YOLO

model = YOLO(r"C:\Users\phuynh\Projects\mineral_yolo\runs\detect\train\weights\best.pt")

model.predict(
    source=r"C:\Users\phuynh\Projects\mineral_yolo\test_images",
    imgsz=640,
    conf=0.25,
    save=True
)