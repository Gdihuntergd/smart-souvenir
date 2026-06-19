"""
AES-128-GCM payload encryption for Smart Souvenir.

Protocol envelope:
{
    "device_id": "gate-esp32-01",
    "boot_id": "A1B2C3D4",
    "counter": "1",
    "nonce": "base64-12-byte-nonce",
    "ciphertext": "base64-ciphertext",
    "tag": "base64-16-byte-tag"
}

Nonce format:
    4 byte boot_id (big endian) + 8 byte counter (big endian)

AAD format:
    device_id|boot_id|counter|endpoint_path

Request and response use different AES keys, so the same nonce may safely be
used in each direction for one request/response pair.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import threading
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


NONCE_SIZE = 12
TAG_SIZE = 16
AES_128_KEY_SIZE = 16
MAX_CIPHERTEXT_BYTES = 16 * 1024


class PayloadCryptoError(ValueError):
    """Base exception for malformed or unauthenticated secure payloads."""


class PayloadCryptoConfigurationError(RuntimeError):
    """Raised when device IDs or AES keys are not configured correctly."""


class PayloadReplayError(PayloadCryptoError):
    """Raised when a counter is not strictly increasing for one boot session."""


@dataclass(frozen=True)
class DeviceKeys:
    device_id: str
    request_key: bytes
    response_key: bytes


@dataclass(frozen=True)
class SecureRequestContext:
    device_id: str
    boot_id: str
    counter: int
    nonce: bytes
    endpoint_path: str
    payload: dict[str, Any]


_counter_lock = threading.Lock()
_last_counters: dict[tuple[str, str], int] = {}


def _hex_key_from_env(name: str) -> bytes:
    value = os.getenv(name, "").strip()

    if not value:
        raise PayloadCryptoConfigurationError(
            f"Environment variable {name} belum diisi"
        )

    try:
        key = bytes.fromhex(value)
    except ValueError as exc:
        raise PayloadCryptoConfigurationError(
            f"{name} harus berupa hexadecimal"
        ) from exc

    if len(key) != AES_128_KEY_SIZE:
        raise PayloadCryptoConfigurationError(
            f"{name} harus tepat 16 byte / 32 karakter hex"
        )

    return key


def _load_device_keys(device_id: str) -> DeviceKeys:
    configured_device_id = os.getenv(
        "GATE_DEVICE_ID",
        "gate-esp32-01",
    ).strip()

    if not device_id or device_id != configured_device_id:
        raise PayloadCryptoError("Device ID tidak terdaftar")

    return DeviceKeys(
        device_id=configured_device_id,
        request_key=_hex_key_from_env("GATE_REQUEST_KEY_HEX"),
        response_key=_hex_key_from_env("GATE_RESPONSE_KEY_HEX"),
    )


def _require_text(envelope: dict[str, Any], field: str) -> str:
    value = envelope.get(field)

    if not isinstance(value, str) or not value.strip():
        raise PayloadCryptoError(f"Field {field} tidak valid")

    return value.strip()


def _parse_counter(value: Any) -> int:
    if isinstance(value, bool):
        raise PayloadCryptoError("Counter tidak valid")

    try:
        counter = int(value)
    except (TypeError, ValueError) as exc:
        raise PayloadCryptoError("Counter tidak valid") from exc

    if counter <= 0 or counter > (2**64 - 1):
        raise PayloadCryptoError("Counter di luar rentang uint64")

    return counter


def _parse_boot_id(value: str) -> tuple[str, bytes]:
    boot_id = value.strip().upper()

    if len(boot_id) != 8:
        raise PayloadCryptoError("boot_id harus 8 karakter hex")

    try:
        boot_bytes = bytes.fromhex(boot_id)
    except ValueError as exc:
        raise PayloadCryptoError("boot_id bukan hexadecimal") from exc

    if len(boot_bytes) != 4:
        raise PayloadCryptoError("boot_id harus 4 byte")

    return boot_id, boot_bytes


def _decode_base64(value: str, field: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PayloadCryptoError(
            f"Field {field} bukan Base64 valid"
        ) from exc

    return decoded


def _build_nonce(boot_bytes: bytes, counter: int) -> bytes:
    return boot_bytes + counter.to_bytes(8, "big")


def _build_aad(
    device_id: str,
    boot_id: str,
    counter: int,
    endpoint_path: str,
) -> bytes:
    return (
        f"{device_id}|{boot_id}|{counter}|{endpoint_path}"
    ).encode("utf-8")


def decrypt_request(
    envelope: dict[str, Any],
    endpoint_path: str,
) -> SecureRequestContext:
    """Validate, authenticate, decrypt, and replay-check one ESP32 request."""
    if not isinstance(envelope, dict):
        raise PayloadCryptoError("Envelope JSON tidak valid")

    device_id = _require_text(envelope, "device_id")
    boot_id, boot_bytes = _parse_boot_id(
        _require_text(envelope, "boot_id")
    )
    counter = _parse_counter(envelope.get("counter"))

    keys = _load_device_keys(device_id)

    nonce = _decode_base64(
        _require_text(envelope, "nonce"),
        "nonce",
    )
    ciphertext = _decode_base64(
        _require_text(envelope, "ciphertext"),
        "ciphertext",
    )
    tag = _decode_base64(
        _require_text(envelope, "tag"),
        "tag",
    )

    if len(nonce) != NONCE_SIZE:
        raise PayloadCryptoError("Nonce harus 12 byte")

    if len(tag) != TAG_SIZE:
        raise PayloadCryptoError("Authentication tag harus 16 byte")

    if not ciphertext or len(ciphertext) > MAX_CIPHERTEXT_BYTES:
        raise PayloadCryptoError("Ukuran ciphertext tidak valid")

    expected_nonce = _build_nonce(boot_bytes, counter)

    if not hmac.compare_digest(nonce, expected_nonce):
        raise PayloadCryptoError(
            "Nonce tidak cocok dengan boot_id dan counter"
        )

    aad = _build_aad(
        device_id,
        boot_id,
        counter,
        endpoint_path,
    )

    session_key = (device_id, boot_id)

    # Counter is checked and committed atomically with authenticated decryption.
    # This prevents two concurrent requests with the same counter from passing.
    with _counter_lock:
        last_counter = _last_counters.get(session_key, 0)

        if counter <= last_counter:
            raise PayloadReplayError(
                "Replay terdeteksi: counter tidak meningkat"
            )

        try:
            plaintext = AESGCM(keys.request_key).decrypt(
                nonce,
                ciphertext + tag,
                aad,
            )
        except InvalidTag as exc:
            raise PayloadCryptoError(
                "Authentication tag request tidak valid"
            ) from exc

        try:
            payload = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PayloadCryptoError(
                "Plaintext request bukan JSON UTF-8 valid"
            ) from exc

        if not isinstance(payload, dict):
            raise PayloadCryptoError(
                "Plaintext request harus berupa object JSON"
            )

        _last_counters[session_key] = counter

    return SecureRequestContext(
        device_id=device_id,
        boot_id=boot_id,
        counter=counter,
        nonce=nonce,
        endpoint_path=endpoint_path,
        payload=payload,
    )


def encrypt_response(
    context: SecureRequestContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Encrypt one Flask response using the response-direction AES key."""
    if not isinstance(payload, dict):
        raise PayloadCryptoError("Response payload harus object JSON")

    keys = _load_device_keys(context.device_id)
    aad = _build_aad(
        context.device_id,
        context.boot_id,
        context.counter,
        context.endpoint_path,
    )

    plaintext = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    encrypted = AESGCM(keys.response_key).encrypt(
        context.nonce,
        plaintext,
        aad,
    )

    ciphertext = encrypted[:-TAG_SIZE]
    tag = encrypted[-TAG_SIZE:]

    return {
        "device_id": context.device_id,
        "boot_id": context.boot_id,
        "counter": str(context.counter),
        "nonce": base64.b64encode(context.nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }
