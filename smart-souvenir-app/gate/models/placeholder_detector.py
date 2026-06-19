"""
YOLO gate detector for Smart Souvenir.

The trained model uses these exact original class names:
- Wanita
- Pria

The public result preserves those labels exactly.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

import cv2
from ultralytics import YOLO


class GateDetector:
    """YOLO-based visitor detector with normalized labels and annotations."""

    VALID_LABELS = {
        "pria": "Pria",
        "wanita": "Wanita",
    }

    # OpenCV uses BGR colors.
    LABEL_COLORS = {
        "Pria": (255, 170, 0),
        "Wanita": (203, 70, 255),
    }
    DEFAULT_COLOR = (0, 220, 90)

    def __init__(self, model_path: str | None = None, confidence_threshold: float = 0.5):
        self.model_path = model_path
        self.confidence_threshold = float(confidence_threshold)
        self.model = None
        self.model_loaded = False
        self.class_names: dict[int, str] | list[str] = {}
        self._load_model()

    @staticmethod
    def _canonical_label(raw_label: Any) -> str:
        """Preserve the model labels Pria and Wanita exactly."""
        label = str(raw_label or "Orang").strip()
        normalized = re.sub(r"[^a-z0-9]", "", label.lower())
        return GateDetector.VALID_LABELS.get(normalized, label)

    def _class_name(self, class_id: int) -> str:
        if isinstance(self.class_names, dict):
            raw_label = self.class_names.get(class_id, f"class_{class_id}")
        elif isinstance(self.class_names, (list, tuple)) and 0 <= class_id < len(self.class_names):
            raw_label = self.class_names[class_id]
        else:
            raw_label = f"class_{class_id}"
        return self._canonical_label(raw_label)

    def _load_model(self) -> None:
        try:
            models_dir = os.path.dirname(__file__)

            if self.model_path and os.path.isdir(self.model_path):
                model_file = os.path.join(self.model_path, "best1.pt")
            elif self.model_path and self.model_path.endswith(".pt"):
                model_file = self.model_path
                if not os.path.isabs(model_file):
                    model_file = os.path.join(models_dir, model_file)
            else:
                model_file = os.path.join(models_dir, "best1.pt")

            if not os.path.exists(model_file):
                print(f"[GateDetector] Model file not found: {model_file}")
                self.model_loaded = False
                return

            self.model = YOLO(model_file)
            self.class_names = self.model.names
            self.model_loaded = True
            print(f"[GateDetector] Model loaded: {model_file}")
            print(f"[GateDetector] Raw classes: {self.class_names}")
            print(
                "[GateDetector] Display classes: "
                f"{[self._class_name(i) for i in range(len(self.class_names))]}"
            )
        except Exception as exc:
            print(f"[GateDetector] Error loading model: {exc}")
            self.model_loaded = False

    def detect(self, frame=None) -> dict[str, Any]:
        timestamp = datetime.now().isoformat()

        if frame is None or not self.model_loaded:
            return {
                "detected": False,
                "person_detected": False,
                "count": 0,
                "detections": [],
                "frame_width": 0,
                "frame_height": 0,
                "timestamp": timestamp,
            }

        frame_height, frame_width = frame.shape[:2]
        predictions = self.model.predict(
            source=frame,
            conf=self.confidence_threshold,
            iou=0.3,
            agnostic_nms=True,
            verbose=False,
        )

        detections: list[dict[str, Any]] = []
        detection_id = 0

        for result in predictions:
            boxes = result.boxes
            if boxes is None:
                continue

            for box in boxes:
                detection_id += 1
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().tolist()
                confidence = float(box.conf[0])
                class_id = int(box.cls[0])
                label = self._class_name(class_id)

                x1_i = max(0, min(frame_width - 1, int(round(x1))))
                y1_i = max(0, min(frame_height - 1, int(round(y1))))
                x2_i = max(x1_i + 1, min(frame_width, int(round(x2))))
                y2_i = max(y1_i + 1, min(frame_height, int(round(y2))))

                detections.append(
                    {
                        "id": detection_id,
                        "class_id": class_id,
                        "label": label,
                        "confidence": round(confidence, 4),
                        "bbox": [x1_i, y1_i, x2_i - x1_i, y2_i - y1_i],
                    }
                )

        detected = bool(detections)
        return {
            "detected": detected,
            "person_detected": detected,
            "count": len(detections),
            "detections": detections,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "timestamp": timestamp,
        }

    def process_frame(self, frame):
        """Return an annotated frame and its structured detection result."""
        results = self.detect(frame)
        annotated_frame = frame.copy() if frame is not None else None

        if annotated_frame is None:
            return None, results

        for detection in results["detections"]:
            x, y, width, height = detection["bbox"]
            confidence = float(detection["confidence"])
            label = detection["label"]
            label_text = f"{label} {confidence * 100:.0f}%"
            color = self.LABEL_COLORS.get(label, self.DEFAULT_COLOR)

            cv2.rectangle(
                annotated_frame,
                (x, y),
                (x + width, y + height),
                color,
                3,
            )

            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.65
            thickness = 2
            (text_width, text_height), baseline = cv2.getTextSize(
                label_text,
                font,
                font_scale,
                thickness,
            )

            label_top = max(0, y - text_height - baseline - 10)
            label_bottom = min(
                annotated_frame.shape[0] - 1,
                label_top + text_height + baseline + 10,
            )
            label_right = min(
                annotated_frame.shape[1] - 1,
                x + text_width + 12,
            )

            cv2.rectangle(
                annotated_frame,
                (x, label_top),
                (label_right, label_bottom),
                color,
                -1,
            )
            cv2.putText(
                annotated_frame,
                label_text,
                (x + 6, label_bottom - baseline - 4),
                font,
                font_scale,
                (255, 255, 255),
                thickness,
                cv2.LINE_AA,
            )

        return annotated_frame, results

    def get_status(self) -> dict[str, Any]:
        display_classes = {}
        try:
            for index in range(len(self.class_names)):
                display_classes[index] = self._class_name(index)
        except TypeError:
            display_classes = {}

        return {
            "model_loaded": self.model_loaded,
            "model_path": self.model_path,
            "confidence_threshold": self.confidence_threshold,
            "is_placeholder": False,
            "classes": display_classes,
            "raw_classes": self.class_names,
        }
