from ultralytics import YOLO

model = YOLO("yolo11n.pt")

model.train(
    data=r"C:\Users\phuynh\Projects\robotray-main\models_v2_phan\robotray_project.v1i.yolov8\data.yaml",
    epochs=100,
    imgsz=640
)