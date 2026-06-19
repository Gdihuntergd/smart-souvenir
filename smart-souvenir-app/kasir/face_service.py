"""
Face recognition service module.

Provides face detection, embedding extraction, and matching capabilities
using DeepFace and OpenCV. Adapted from the original face_recognition project
to work with the unified member table.
"""

import base64
import io
import json
import math
import os
import tempfile
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


MODEL_NAME = os.getenv("DEEPFACE_MODEL", "Facenet512")
DETECTOR_BACKEND = os.getenv("DEEPFACE_DETECTOR", "opencv")
SIMILARITY_THRESHOLD = float(os.getenv("FACE_SIMILARITY_THRESHOLD", "0.60"))
MAX_LIVE_FACES = int(os.getenv("FACE_MAX_LIVE_FACES", "20"))
MIN_FACE_SIZE = int(os.getenv("FACE_MIN_SIZE", "34"))


def _load_deepface():
    try:
        from deepface import DeepFace
    except ImportError as exc:
        raise RuntimeError(
            "DeepFace belum terinstall. Gunakan Python 3.10/3.11 lalu jalankan `pip install -r requirements.txt`."
        ) from exc

    return DeepFace


def decode_base64_image(image_data):
    if not image_data:
        raise ValueError("Gambar kosong")

    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    raw = base64.b64decode(image_data)
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    return image


def _save_temp_image(image):
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    temp_path = Path(temp.name)
    temp.close()
    image.save(temp_path, format="JPEG", quality=92)
    return temp_path


@lru_cache(maxsize=1)
def _opencv_face_detector():
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        raise RuntimeError("OpenCV face detector tidak tersedia")
    return detector


def _embedding_values(representation):
    embedding = representation.get("embedding")
    if not embedding:
        raise ValueError("Embedding wajah gagal dibuat")
    return [float(value) for value in embedding]


def _bounded_box(area, width, height):
    x = max(0, int(area.get("x") or 0))
    y = max(0, int(area.get("y") or 0))
    w = max(1, int(area.get("w") or 1))
    h = max(1, int(area.get("h") or 1))

    if x + w > width:
        w = max(1, width - x)
    if y + h > height:
        h = max(1, height - y)

    return {"x": x, "y": y, "w": w, "h": h}


def _gray_image(image):
    rgb = np.array(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return cv2.equalizeHist(gray)


def _match_payload(row, score):
    """Build match payload — adapted for unified member table.

    The `row` dict comes from a JOIN query and contains:
      - member_nik (from member_embeddings)
      - nama       (from member table)
      - id         (embedding id)
      - embedding  (serialized)
    """
    return {
        "member_nik": row["member_nik"],
        "nama": row["nama"],
        "score": score,
        "embedding_id": row["id"],
    }


def representations_from_image(image, enforce_detection=True, max_faces=None):
    DeepFace = _load_deepface()
    temp_path = _save_temp_image(image)
    try:
        representations = DeepFace.represent(
            img_path=str(temp_path),
            model_name=MODEL_NAME,
            detector_backend=DETECTOR_BACKEND,
            enforce_detection=enforce_detection,
            align=True,
            max_faces=max_faces,
        )
    finally:
        temp_path.unlink(missing_ok=True)

    if not representations:
        raise ValueError("Wajah tidak terdeteksi")

    return representations


def embedding_from_image(image):
    representations = representations_from_image(image, enforce_detection=True, max_faces=2)
    if len(representations) > 1:
        raise ValueError("Foto enrollment hanya boleh berisi satu wajah")

    return _embedding_values(representations[0])


def embedding_from_upload(file_storage):
    image = Image.open(file_storage.stream).convert("RGB")
    return embedding_from_image(image)


def embedding_from_data_url(image_data):
    image = decode_base64_image(image_data)
    representations = representations_from_image(image, enforce_detection=True, max_faces=1)
    return _embedding_values(representations[0])


def detections_from_data_url(image_data):
    image = decode_base64_image(image_data)
    width, height = image.size
    representations = representations_from_image(image, enforce_detection=True, max_faces=MAX_LIVE_FACES)

    detections = []
    for representation in representations:
        area = representation.get("facial_area") or {}
        if not area:
            continue

        detections.append(
            {
                "embedding": _embedding_values(representation),
                "box": _bounded_box(area, width, height),
                "confidence": float(representation.get("face_confidence") or 0),
            }
        )

    if not detections:
        raise ValueError("Wajah tidak terdeteksi")

    return {"width": width, "height": height, "detections": detections}


def fast_face_boxes_from_data_url(image_data):
    image = decode_base64_image(image_data)
    width, height = image.size
    boxes = _opencv_face_detector().detectMultiScale(
        _gray_image(image),
        scaleFactor=1.08,
        minNeighbors=4,
        minSize=(MIN_FACE_SIZE, MIN_FACE_SIZE),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )

    detections = []
    for (x, y, w, h) in boxes:
        detections.append(
            {
                "status": "DETECTING",
                "label": "VERIFYING",
                "score": None,
                "confidence": None,
                "box": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
            }
        )

    detections.sort(key=lambda item: item["box"]["w"] * item["box"]["h"], reverse=True)
    return {"width": width, "height": height, "detections": detections[:MAX_LIVE_FACES]}


def cosine_similarity(left, right):
    a = np.array(left, dtype=np.float32)
    b = np.array(right, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0 or math.isnan(denom):
        return 0.0
    return float(np.dot(a, b) / denom)


def serialize_embedding(embedding):
    return json.dumps(embedding, separators=(",", ":"))


def deserialize_embedding(value):
    return json.loads(value)


def find_best_match(query_embedding, rows):
    best = score_best_match(query_embedding, rows)
    if best and best["score"] >= SIMILARITY_THRESHOLD:
        return best
    return None


def score_best_match(query_embedding, rows):
    best = None
    for row in rows:
        stored = deserialize_embedding(row["embedding"])
        score = cosine_similarity(query_embedding, stored)
        if best is None or score > best["score"]:
            best = _match_payload(row, score)
    return best
