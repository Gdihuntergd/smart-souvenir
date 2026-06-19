from __future__ import annotations

import base64
import binascii
import json
import threading
import time
from datetime import datetime
from typing import Any

import cv2
import numpy as np
from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
)
from flask_socketio import emit

from .camera_handler import CameraFrameGenerator, CameraHandler
from .config import GateConfig
from .database import GateStats, VisitorLog, db
from .models.placeholder_detector import GateDetector
from .payload_crypto import (
    PayloadCryptoConfigurationError,
    PayloadCryptoError,
    PayloadReplayError,
    decrypt_request,
    encrypt_response,
)


# ============================================================
# Blueprint
# ============================================================

gate_bp = Blueprint(
    "gate",
    __name__,
    url_prefix="/gate",
    template_folder="templates",
    static_folder="static",
)


# ============================================================
# Service objects
# ============================================================

camera_handler = CameraHandler(
    camera_index=GateConfig.CAMERA_INDEX,
    width=GateConfig.CAMERA_WIDTH,
    height=GateConfig.CAMERA_HEIGHT,
)

frame_generator = CameraFrameGenerator(
    width=GateConfig.CAMERA_WIDTH,
    height=GateConfig.CAMERA_HEIGHT,
)

detector = GateDetector(
    model_path=GateConfig.ML_MODEL_PATH,
    confidence_threshold=GateConfig.DETECTION_CONFIDENCE,
)


# ============================================================
# Synchronization
# ============================================================

# Melindungi proses start/stop kamera.
camera_lock = threading.RLock()

# Melindungi inferensi model agar stream browser, REST API,
# dan Socket.IO tidak menjalankan model secara bersamaan.
detector_lock = threading.RLock()

# Melindungi gate_state.
gate_state_lock = threading.RLock()

# Melindungi cache hasil deteksi.
detection_cache_lock = threading.RLock()


# ============================================================
# Runtime configuration
# ============================================================

CAMERA_START_TIMEOUT_SECONDS = 2.0
CAMERA_FRAME_POLL_SECONDS = 0.05

# Hasil deteksi browser dapat dipakai ESP32 selama masih segar.
DETECTION_CACHE_MAX_AGE_SECONDS = 0.75

# Stream kira-kira 30 FPS.
STREAM_FRAME_DELAY_SECONDS = 0.033

# Kualitas JPEG untuk MJPEG.
JPEG_QUALITY = 80


# ============================================================
# Gate state
# ============================================================

gate_state: dict[str, Any] = {
    "status": "open",
    "auto_mode": True,
    "total_visitors_today": 0,
    "last_detection": None,
    "camera_active": False,
    "camera_source": None,
}


# ============================================================
# Detection cache
# ============================================================

detection_cache: dict[str, Any] = {
    "person_detected": False,
    "count": 0,
    "confidence": 0.0,
    "updated_monotonic": 0.0,
    "updated_at": None,
}


# ============================================================
# Utility helpers
# ============================================================

def _detector_status() -> dict[str, Any]:
    """Mengambil status detector dalam bentuk dictionary."""
    try:
        status = detector.get_status()
        return status if isinstance(status, dict) else {}
    except Exception:
        current_app.logger.exception("Gagal membaca status detector")
        return {}


def _detector_is_ready() -> bool:
    """
    Menentukan apakah detector siap.

    Beberapa implementasi detector menggunakan nama field berbeda.
    Bila status tidak menyediakan indikator kesiapan, detector dianggap
    siap dan error aktual akan ditangani saat inferensi.
    """
    status = _detector_status()

    readiness_keys = (
        "model_loaded",
        "loaded",
        "ready",
        "available",
    )

    for key in readiness_keys:
        if key in status:
            return bool(status[key])

    return True


def _set_camera_state(active: bool, source: str | None) -> None:
    with gate_state_lock:
        gate_state["camera_active"] = active
        gate_state["camera_source"] = source


def _camera_running() -> bool:
    return bool(getattr(camera_handler, "is_running", False))


def _start_usb_camera(
    camera_index: int | None = None,
) -> bool:
    """
    Memulai kamera USB secara thread-safe.

    Tidak melakukan start ulang jika kamera sudah aktif.
    """
    with camera_lock:
        if _camera_running():
            _set_camera_state(True, "usb")
            return True

        index = (
            GateConfig.CAMERA_INDEX
            if camera_index is None
            else camera_index
        )

        try:
            success = bool(
                camera_handler.start_usb_camera(
                    camera_index=index
                )
            )
        except TypeError:
            # Kompatibilitas jika implementasi lama tidak menerima argumen.
            success = bool(camera_handler.start_usb_camera())
        except Exception:
            current_app.logger.exception(
                "Gagal memulai kamera USB"
            )
            success = False

        _set_camera_state(
            success,
            "usb" if success else None,
        )

        return success


def _start_ip_camera(stream_url: str) -> bool:
    with camera_lock:
        try:
            success = bool(
                camera_handler.start_ip_camera(stream_url)
            )
        except Exception:
            current_app.logger.exception(
                "Gagal memulai kamera IP"
            )
            success = False

        _set_camera_state(
            success,
            "ip" if success else None,
        )

        return success


def _stop_camera() -> None:
    with camera_lock:
        try:
            camera_handler.stop()
        finally:
            _set_camera_state(False, None)


def _wait_for_camera_frame(
    timeout_seconds: float = CAMERA_START_TIMEOUT_SECONDS,
) -> np.ndarray | None:
    """
    Menunggu frame kamera tersedia hingga timeout.

    Penting karena start_usb_camera biasanya memakai background thread,
    sehingga frame pertama tidak langsung tersedia.
    """
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        frame = camera_handler.get_frame()

        if frame is not None:
            return frame

        time.sleep(CAMERA_FRAME_POLL_SECONDS)

    return None


def _ensure_camera_frame() -> tuple[np.ndarray | None, str | None]:
    """
    Memastikan kamera aktif dan frame tersedia.

    Returns:
        (frame, error_message)
    """
    if not _camera_running():
        if not _start_usb_camera():
            return None, "Kamera USB gagal dibuka"

    frame = _wait_for_camera_frame()

    if frame is None:
        return None, "Frame kamera belum tersedia"

    return frame, None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_confidence(results: dict[str, Any]) -> float:
    """
    Mengambil confidence rata-rata dari format hasil detector.

    Mendukung:
    - results["confidence"]
    - results["confidence_avg"]
    - results["detections"][i]["confidence"]
    """
    if "confidence" in results:
        return _safe_float(results.get("confidence"))

    if "confidence_avg" in results:
        return _safe_float(results.get("confidence_avg"))

    detections = results.get("detections") or []

    confidences = [
        _safe_float(item.get("confidence"))
        for item in detections
        if isinstance(item, dict)
    ]

    confidences = [
        value for value in confidences if value > 0
    ]

    if not confidences:
        return 0.0

    return sum(confidences) / len(confidences)


def _normalize_detection_results(
    results: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Menormalisasi output detector menjadi kontrak API gate.

    Detector saat ini menggunakan:
        detected
        count
        detections
        timestamp
    """
    results = results or {}

    count = int(results.get("count") or 0)

    person_detected = bool(
        results.get(
            "person_detected",
            results.get("detected", count > 0),
        )
    )

    if person_detected and count <= 0:
        count = 1

    return {
        "person_detected": person_detected,
        "count": count,
        "confidence": round(
            _extract_confidence(results),
            4,
        ),
        "timestamp": (
            results.get("timestamp")
            or datetime.now().isoformat()
        ),
    }


def _update_detection_cache(
    normalized_results: dict[str, Any],
) -> None:
    now_monotonic = time.monotonic()

    with detection_cache_lock:
        detection_cache.update(
            {
                "person_detected": bool(
                    normalized_results[
                        "person_detected"
                    ]
                ),
                "count": int(
                    normalized_results["count"]
                ),
                "confidence": float(
                    normalized_results["confidence"]
                ),
                "updated_monotonic": now_monotonic,
                "updated_at": normalized_results[
                    "timestamp"
                ],
            }
        )


def _get_detection_cache(
    max_age_seconds: float = (
        DETECTION_CACHE_MAX_AGE_SECONDS
    ),
) -> dict[str, Any] | None:
    now_monotonic = time.monotonic()

    with detection_cache_lock:
        updated_monotonic = float(
            detection_cache.get(
                "updated_monotonic",
                0.0,
            )
        )

        if updated_monotonic <= 0:
            return None

        age_seconds = now_monotonic - updated_monotonic

        if age_seconds > max_age_seconds:
            return None

        return {
            "person_detected": bool(
                detection_cache["person_detected"]
            ),
            "count": int(detection_cache["count"]),
            "confidence": float(
                detection_cache["confidence"]
            ),
            "updated_at": detection_cache[
                "updated_at"
            ],
            "frame_age_ms": int(
                age_seconds * 1000
            ),
        }


def _detect_frame(
    frame: np.ndarray,
    *,
    annotate: bool,
) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    """
    Menjalankan inferensi secara thread-safe.

    Returns:
        annotated_frame,
        raw_results,
        normalized_results
    """
    with detector_lock:
        if annotate:
            annotated_frame, raw_results = (
                detector.process_frame(frame)
            )
        else:
            raw_results = detector.detect(frame)
            annotated_frame = frame

    if not isinstance(raw_results, dict):
        raw_results = {}

    normalized = _normalize_detection_results(
        raw_results
    )

    _update_detection_cache(normalized)

    return annotated_frame, raw_results, normalized


def _detection_response(
    normalized: dict[str, Any],
    *,
    source: str,
    frame_age_ms: int = 0,
) -> dict[str, Any]:
    return {
        "ok": True,
        "camera_ok": True,
        "model_ok": True,
        "person_detected": bool(
            normalized["person_detected"]
        ),
        "count": int(normalized["count"]),
        "confidence": float(
            normalized["confidence"]
        ),
        "frame_age_ms": int(frame_age_ms),
        "source": source,
        "error": None,
    }


def _error_response(
    message: str,
    *,
    status_code: int,
    camera_ok: bool,
    model_ok: bool,
):
    return (
        jsonify(
            {
                "ok": False,
                "camera_ok": camera_ok,
                "model_ok": model_ok,
                "person_detected": False,
                "count": 0,
                "confidence": 0.0,
                "frame_age_ms": -1,
                "source": "error",
                "error": message,
            }
        ),
        status_code,
    )


def _store_visitor_log(
    raw_results: dict[str, Any],
    normalized: dict[str, Any],
) -> None:
    """Menyimpan hasil deteksi ke database."""
    if not normalized["person_detected"]:
        return

    with gate_state_lock:
        gate_state["total_visitors_today"] += int(
            normalized["count"]
        )
        gate_state["last_detection"] = normalized[
            "timestamp"
        ]
        current_gate_status = gate_state["status"]

    log = VisitorLog(
        visitor_count=int(normalized["count"]),
        confidence_avg=float(
            normalized["confidence"]
        ),
        gate_status=current_gate_status,
        detection_data=json.dumps(
            raw_results,
            default=str,
        ),
    )

    try:
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Gagal menyimpan visitor log"
        )


def _decode_base64_image(
    image_b64: str,
) -> np.ndarray:
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    image_bytes = base64.b64decode(
        image_b64,
        validate=True,
    )

    image_array = np.frombuffer(
        image_bytes,
        dtype=np.uint8,
    )

    frame = cv2.imdecode(
        image_array,
        cv2.IMREAD_COLOR,
    )

    if frame is None:
        raise ValueError(
            "Data gambar tidak dapat didekode"
        )

    return frame


# ============================================================
# Page routes
# ============================================================

@gate_bp.get("/")
def dashboard():
    with gate_state_lock:
        state_snapshot = dict(gate_state)

    return render_template(
        "dashboard.html",
        gate_state=state_snapshot,
    )


@gate_bp.get("/logs")
def visitor_logs():
    page = request.args.get(
        "page",
        1,
        type=int,
    )

    per_page = 20

    search = request.args.get(
        "search",
        "",
        type=str,
    ).strip()

    date_filter = request.args.get(
        "date",
        "",
        type=str,
    ).strip()

    query = VisitorLog.query

    if date_filter:
        try:
            filter_date = datetime.strptime(
                date_filter,
                "%Y-%m-%d",
            ).date()

            query = query.filter(
                db.func.date(
                    VisitorLog.detected_at
                )
                == filter_date
            )
        except ValueError:
            pass

    if search:
        like_pattern = f"%{search}%"

        query = query.filter(
            db.or_(
                VisitorLog.gate_status.ilike(
                    like_pattern
                ),
                db.cast(
                    VisitorLog.visitor_count,
                    db.String,
                ).ilike(like_pattern),
                db.cast(
                    VisitorLog.detected_at,
                    db.String,
                ).ilike(like_pattern),
            )
        )

    logs = query.order_by(
        VisitorLog.detected_at.desc()
    ).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    with gate_state_lock:
        state_snapshot = dict(gate_state)

    return render_template(
        "logs.html",
        logs=logs,
        gate_state=state_snapshot,
        search=search,
        date_filter=date_filter,
    )


@gate_bp.get("/settings")
def settings_page():
    with gate_state_lock:
        state_snapshot = dict(gate_state)

    return render_template(
        "settings.html",
        gate_state=state_snapshot,
        detector_status=_detector_status(),
    )


# ============================================================
# Gate APIs
# ============================================================

@gate_bp.get("/api/gate/status")
def api_gate_status():
    with gate_state_lock:
        state_snapshot = dict(gate_state)

    state_snapshot["detector"] = _detector_status()
    state_snapshot["camera_status"] = (
        camera_handler.get_status()
    )

    cached_detection = _get_detection_cache()

    state_snapshot["latest_detection"] = (
        cached_detection
    )

    return jsonify(state_snapshot)


@gate_bp.post("/api/gate/toggle")
def api_gate_toggle():
    with gate_state_lock:
        gate_state["status"] = (
            "closed"
            if gate_state["status"] == "open"
            else "open"
        )

        status = gate_state["status"]

    return jsonify(
        {
            "success": True,
            "status": status,
        }
    )


# ============================================================
# Camera APIs
# ============================================================

@gate_bp.post("/api/camera/start")
def api_camera_start():
    data = request.get_json(silent=True) or {}
    source = str(data.get("source", "usb")).lower()

    _stop_camera()

    if source == "usb":
        camera_index = int(
            data.get(
                "index",
                GateConfig.CAMERA_INDEX,
            )
        )

        success = _start_usb_camera(
            camera_index=camera_index
        )

    elif source == "ip":
        stream_url = str(
            data.get("url", "")
        ).strip()

        if not stream_url:
            return jsonify(
                {
                    "success": False,
                    "error": "Stream URL diperlukan",
                }
            ), 400

        success = _start_ip_camera(stream_url)

    else:
        return jsonify(
            {
                "success": False,
                "error": "Tipe sumber kamera tidak valid",
            }
        ), 400

    if not success:
        return jsonify(
            {
                "success": False,
                "error": "Kamera gagal dimulai",
            }
        ), 500

    frame = _wait_for_camera_frame()

    if frame is None:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Kamera aktif tetapi frame "
                    "belum tersedia"
                ),
            }
        ), 503

    return jsonify(
        {
            "success": True,
            "source": source,
            "camera_status": (
                camera_handler.get_status()
            ),
        }
    )


@gate_bp.post("/api/camera/stop")
def api_camera_stop():
    _stop_camera()

    return jsonify(
        {
            "success": True,
        }
    )


@gate_bp.get("/api/camera/status")
def api_camera_status():
    status = camera_handler.get_status()

    with gate_state_lock:
        status["gate_camera_active"] = gate_state[
            "camera_active"
        ]
        status["gate_camera_source"] = gate_state[
            "camera_source"
        ]

    return jsonify(status)


# ============================================================
# Detection APIs
# ============================================================

@gate_bp.post("/api/detection/run")
def api_run_detection():
    frame = None

    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")

    if image_b64:
        try:
            frame = _decode_base64_image(
                str(image_b64)
            )
        except (
            ValueError,
            binascii.Error,
        ) as exc:
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        f"Data gambar tidak valid: {exc}"
                    ),
                }
            ), 400

    if frame is None:
        frame, camera_error = _ensure_camera_frame()

        if frame is None:
            return _error_response(
                camera_error
                or "Frame kamera tidak tersedia",
                status_code=503,
                camera_ok=False,
                model_ok=_detector_is_ready(),
            )

    if not _detector_is_ready():
        return _error_response(
            "Model deep learning belum siap",
            status_code=503,
            camera_ok=True,
            model_ok=False,
        )

    try:
        _, raw_results, normalized = _detect_frame(
            frame,
            annotate=False,
        )
    except Exception as exc:
        current_app.logger.exception(
            "Inferensi detection/run gagal"
        )

        return _error_response(
            str(exc),
            status_code=500,
            camera_ok=True,
            model_ok=False,
        )

    _store_visitor_log(
        raw_results,
        normalized,
    )

    response = dict(raw_results)
    response.update(
        _detection_response(
            normalized,
            source="manual_detection",
        )
    )

    return jsonify(response)


@gate_bp.get("/api/detection/check")
def api_detection_check():
    """
    Endpoint utama untuk ESP32.

    Menggunakan cache hasil stream browser jika masih segar.
    Jika cache tidak tersedia, endpoint menjalankan inferensi baru.
    """
    if not _detector_is_ready():
        return _error_response(
            "Model deep learning belum siap",
            status_code=503,
            camera_ok=_camera_running(),
            model_ok=False,
        )

    cached = _get_detection_cache()

    if cached is not None:
        return jsonify(
            {
                "ok": True,
                "camera_ok": _camera_running(),
                "model_ok": True,
                "person_detected": cached[
                    "person_detected"
                ],
                "count": cached["count"],
                "confidence": cached[
                    "confidence"
                ],
                "frame_age_ms": cached[
                    "frame_age_ms"
                ],
                "source": "detection_cache",
                "error": None,
            }
        )

    frame, camera_error = _ensure_camera_frame()

    if frame is None:
        return _error_response(
            camera_error
            or "Frame kamera tidak tersedia",
            status_code=503,
            camera_ok=False,
            model_ok=True,
        )

    started_at = time.monotonic()

    try:
        _, _, normalized = _detect_frame(
            frame,
            annotate=False,
        )
    except Exception as exc:
        current_app.logger.exception(
            "Inferensi detection/check gagal"
        )

        return _error_response(
            str(exc),
            status_code=500,
            camera_ok=True,
            model_ok=False,
        )

    inference_age_ms = int(
        (time.monotonic() - started_at) * 1000
    )

    return jsonify(
        _detection_response(
            normalized,
            source="fresh_inference",
            frame_age_ms=inference_age_ms,
        )
    )



# ============================================================
# Secure detection API (AES-128-GCM payload)
# ============================================================

def _elapsed_us(start_ns: int) -> int:
    """Mengubah selisih perf_counter_ns menjadi mikrodetik."""
    return max(
        0,
        (time.perf_counter_ns() - start_ns) // 1000,
    )


def _make_json_payload(view_result) -> tuple[dict[str, Any], int]:
    """
    Mengubah hasil view Flask menjadi dictionary JSON dan status HTTP.

    Fungsi ini dipakai agar endpoint secure menggunakan logika deteksi
    yang sama persis dengan endpoint plaintext /api/detection/check.
    """
    response = current_app.make_response(view_result)
    payload = response.get_json(silent=True)

    if not isinstance(payload, dict):
        payload = {
            "ok": False,
            "person_detected": False,
            "count": 0,
            "error": "Respons internal deteksi bukan JSON object",
        }

    return payload, int(response.status_code)


@gate_bp.post("/api/secure/detection-check")
def api_secure_detection_check():
    """
    Endpoint AES-128-GCM untuk ESP32.

    Request plaintext sebelum dienkripsi:
        {
            "event": "person_detection",
            "ir_detected": true
        }

    Endpoint plaintext lama tetap tersedia di:
        GET /gate/api/detection/check
    """
    endpoint_path = "/gate/api/secure/detection-check"
    envelope = request.get_json(silent=True)

    decrypt_started = time.perf_counter_ns()

    try:
        crypto_context = decrypt_request(
            envelope,
            endpoint_path,
        )
    except PayloadReplayError as exc:
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 409
    except PayloadCryptoConfigurationError as exc:
        current_app.logger.error(
            "Konfigurasi secure detection tidak valid: %s",
            exc,
        )
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 500
    except PayloadCryptoError as exc:
        current_app.logger.warning(
            "Secure detection request ditolak: %s",
            exc,
        )
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 400

    server_decrypt_us = _elapsed_us(decrypt_started)
    process_started = time.perf_counter_ns()

    try:
        event_name = str(
            crypto_context.payload.get("event", "")
        ).strip()

        if event_name != "person_detection":
            business_payload = {
                "ok": False,
                "person_detected": False,
                "count": 0,
                "error": "Event harus person_detection",
            }
            business_status = 422
        else:
            business_payload, business_status = (
                _make_json_payload(
                    api_detection_check()
                )
            )
    except Exception:
        current_app.logger.exception(
            "Pemrosesan secure detection gagal"
        )
        business_payload = {
            "ok": False,
            "person_detected": False,
            "count": 0,
            "error": "Internal secure detection error",
        }
        business_status = 500

    server_process_us = _elapsed_us(process_started)

    response_plaintext = dict(business_payload)
    response_plaintext["service_http_code"] = (
        business_status
    )
    response_plaintext["server_decrypt_us"] = (
        server_decrypt_us
    )
    response_plaintext["server_process_us"] = (
        server_process_us
    )

    encrypt_started = time.perf_counter_ns()

    try:
        response_envelope = encrypt_response(
            crypto_context,
            response_plaintext,
        )
    except (
        PayloadCryptoError,
        PayloadCryptoConfigurationError,
    ) as exc:
        current_app.logger.exception(
            "Enkripsi response secure detection gagal"
        )
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
            }
        ), 500

    # Nilai ini diletakkan di envelope agar ESP32 dapat mencetak
    # waktu enkripsi server pada Serial Monitor.
    response_envelope["server_encrypt_us"] = (
        _elapsed_us(encrypt_started)
    )

    # HTTP 200 berarti pertukaran envelope berhasil. Status proses
    # deteksi asli berada di service_http_code di dalam ciphertext.
    return jsonify(response_envelope), 200


# ============================================================
# Log and statistics APIs
# ============================================================

@gate_bp.get("/api/logs")
def api_get_logs():
    page = request.args.get(
        "page",
        1,
        type=int,
    )

    per_page = request.args.get(
        "per_page",
        20,
        type=int,
    )

    search = request.args.get(
        "search",
        "",
        type=str,
    ).strip()

    date_filter = request.args.get(
        "date",
        "",
        type=str,
    ).strip()

    query = VisitorLog.query

    if date_filter:
        try:
            filter_date = datetime.strptime(
                date_filter,
                "%Y-%m-%d",
            ).date()

            query = query.filter(
                db.func.date(
                    VisitorLog.detected_at
                )
                == filter_date
            )
        except ValueError:
            pass

    if search:
        like_pattern = f"%{search}%"

        query = query.filter(
            db.or_(
                VisitorLog.gate_status.ilike(
                    like_pattern
                ),
                db.cast(
                    VisitorLog.visitor_count,
                    db.String,
                ).ilike(like_pattern),
                db.cast(
                    VisitorLog.detected_at,
                    db.String,
                ).ilike(like_pattern),
            )
        )

    logs = query.order_by(
        VisitorLog.detected_at.desc()
    ).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    return jsonify(
        {
            "logs": [
                log.to_dict()
                for log in logs.items
            ],
            "total": logs.total,
            "pages": logs.pages,
            "current_page": logs.page,
        }
    )


@gate_bp.get("/api/stats")
def api_get_stats():
    today = datetime.now().date()

    today_logs = VisitorLog.query.filter(
        db.func.date(
            VisitorLog.detected_at
        )
        == today
    ).all()

    total_today = sum(
        log.visitor_count
        for log in today_logs
    )

    detections_today = len(today_logs)

    avg_confidence = (
        sum(
            log.confidence_avg
            for log in today_logs
        )
        / max(detections_today, 1)
    )

    hourly: dict[int, int] = {}

    for log in today_logs:
        hour = log.detected_at.hour
        hourly[hour] = (
            hourly.get(hour, 0)
            + log.visitor_count
        )

    peak_hour = (
        max(hourly, key=hourly.get)
        if hourly
        else None
    )

    return jsonify(
        {
            "today": {
                "total_visitors": total_today,
                "total_detections": (
                    detections_today
                ),
                "avg_confidence": round(
                    avg_confidence,
                    4,
                ),
                "peak_hour": peak_hour,
            },
            "hourly": hourly,
        }
    )


@gate_bp.post("/api/settings/detector")
def api_update_detector_settings():
    data = request.get_json(silent=True) or {}

    if "confidence_threshold" in data:
        try:
            threshold = float(
                data["confidence_threshold"]
            )
        except (TypeError, ValueError):
            return jsonify(
                {
                    "success": False,
                    "error": (
                        "confidence_threshold "
                        "harus berupa angka"
                    ),
                }
            ), 400

        if not 0.0 <= threshold <= 1.0:
            return jsonify(
                {
                    "success": False,
                    "error": (
                        "confidence_threshold "
                        "harus antara 0 dan 1"
                    ),
                }
            ), 400

        with detector_lock:
            detector.confidence_threshold = threshold

    return jsonify(
        {
            "success": True,
            "detector": _detector_status(),
        }
    )


# ============================================================
# Video streaming
# ============================================================

def generate_video_stream(
    use_detection: bool = False,
):
    """
    Generator MJPEG.

    Bila use_detection=True, hasil inferensi disimpan ke cache sehingga
    endpoint ESP32 dapat menggunakan hasil yang sama dengan browser.
    """
    while True:
        frame = camera_handler.get_frame()

        if frame is None:
            frame = frame_generator.generate_frame()

        if frame is None:
            time.sleep(STREAM_FRAME_DELAY_SECONDS)
            continue

        if use_detection:
            try:
                frame, _, _ = _detect_frame(
                    frame,
                    annotate=True,
                )
            except Exception:
                current_app.logger.exception(
                    "Inferensi video stream gagal"
                )

        encode_success, buffer = cv2.imencode(
            ".jpg",
            frame,
            [
                cv2.IMWRITE_JPEG_QUALITY,
                JPEG_QUALITY,
            ],
        )

        if not encode_success:
            time.sleep(STREAM_FRAME_DELAY_SECONDS)
            continue

        frame_bytes = buffer.tobytes()

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame_bytes
            + b"\r\n"
        )

        time.sleep(STREAM_FRAME_DELAY_SECONDS)


@gate_bp.get("/video/feed")
def video_feed():
    return Response(
        generate_video_stream(
            use_detection=False
        ),
        mimetype=(
            "multipart/x-mixed-replace;"
            " boundary=frame"
        ),
    )


@gate_bp.get("/video/detection")
def video_detection_feed():
    return Response(
        generate_video_stream(
            use_detection=True
        ),
        mimetype=(
            "multipart/x-mixed-replace;"
            " boundary=frame"
        ),
    )


# ============================================================
# Socket.IO
# ============================================================

def register_gate_socketio(socketio) -> None:
    @socketio.on("connect")
    def handle_connect():
        with gate_state_lock:
            status = gate_state["status"]
            camera_active = gate_state[
                "camera_active"
            ]
            camera_source = gate_state[
                "camera_source"
            ]

        emit(
            "gate_status",
            {
                "status": status,
            },
        )

        emit(
            "camera_status",
            {
                "active": camera_active,
                "source": camera_source,
            },
        )

    @socketio.on("request_detection")
    def handle_detection_request():
        frame, camera_error = _ensure_camera_frame()

        if frame is None:
            emit(
                "detection_result",
                {
                    "ok": False,
                    "person_detected": False,
                    "count": 0,
                    "error": camera_error,
                },
            )
            return

        try:
            _, raw_results, normalized = (
                _detect_frame(
                    frame,
                    annotate=False,
                )
            )
        except Exception as exc:
            current_app.logger.exception(
                "Inferensi Socket.IO gagal"
            )

            emit(
                "detection_result",
                {
                    "ok": False,
                    "person_detected": False,
                    "count": 0,
                    "error": str(exc),
                },
            )
            return

        response = dict(raw_results)
        response.update(
            _detection_response(
                normalized,
                source="socketio",
            )
        )

        emit(
            "detection_result",
            response,
        )


# ============================================================
# Database initialization
# ============================================================

def init_gate_db(app) -> None:
    with app.app_context():
        db.create_all()
        print("[Gate] Database initialized")
