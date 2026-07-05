import os

def export_model():
    print("Initializing YOLO TensorRT Export...")
    try:
        from ultralytics import YOLO
    except ImportError:
        print("Error: ultralytics is not installed. Please install it with 'pip install ultralytics'")
        return

    try:
        import tensorrt
    except ImportError:
        print("Error: tensorrt is not installed. Please install it with 'pip install tensorrt'")
        return

    model_dir = os.path.join(os.path.dirname(__file__), "monitor_app", "models")
    model_path = os.path.join(model_dir, "best.pt")

    if not os.path.exists(model_path):
        print(f"Error: Could not find the YOLO model at {model_path}")
        return

    print(f"Loading model from {model_path}")
    model = YOLO(model_path)

    print("Exporting model to TensorRT (.engine)...")
    print("This may take several minutes and is highly hardware-dependent.")
    
    # Export parameters according to config.yaml
    model.export(format="engine", half=True, imgsz=960, device=0)

    engine_path = os.path.join(model_dir, "best.engine")
    if os.path.exists(engine_path):
        print(f"\nSuccess! Exported engine saved to {engine_path}")
    else:
        print("\nExport completed, but the .engine file might have been saved in the root directory.")
        # Sometimes ultralytics saves it next to the script or in the weights folder.
        
if __name__ == "__main__":
    export_model()
