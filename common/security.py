"""Authenticated encryption and replay protection for UDP datagrams."""

import hashlib
import hmac
import os
import sqlite3
import struct
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Version, message kind, sender length, sequence, Unix milliseconds, payload length.
_HEADER = struct.Struct("!4sBBQQI")
_MAGIC = b"DMS2"
_NONCE_SIZE = 12
_GCM_TAG_SIZE = 16
_ENCRYPTION_LABEL = b"datamesh/udp/aes-gcm/v1"
_TAG_SIZE = hashlib.sha256().digest_size


class SecurityError(ValueError):
    """An authenticated datagram could not be trusted."""


def seal(
    kind: int, sender: str, sequence: int, timestamp_ms: int, payload: bytes, key: bytes
) -> bytes:
    """Authenticate the exact wire representation, including sender and metadata."""
    name = sender.encode("utf-8")
    if not name or len(name) > 255 or not 0 <= kind <= 255 or not 0 < sequence < 2**63:
        raise ValueError("invalid sender, message kind or sequence")
    if len(key) < 32:
        raise ValueError("HMAC key must contain at least 32 bytes")
    nonce = os.urandom(_NONCE_SIZE)
    header = _HEADER.pack(
        _MAGIC, kind, len(name), sequence, timestamp_ms, len(payload) + _GCM_TAG_SIZE
    )
    associated_data = header + name
    encryption_key = hmac.digest(key, _ENCRYPTION_LABEL, "sha256")
    ciphertext = AESGCM(encryption_key).encrypt(nonce, payload, associated_data)
    message = associated_data + nonce + ciphertext
    return message + hmac.digest(key, message, "sha256")


def open_envelope(
    data: bytes, keys: dict[str, bytes], *, now_ms: int | None = None, window_ms: int = 5000
) -> tuple[int, str, int, bytes]:
    """Verify signature and freshness before returning an untrusted payload."""
    if len(data) < _HEADER.size + _TAG_SIZE:
        raise SecurityError("truncated envelope")
    magic, kind, name_len, seq, timestamp, payload_len = _HEADER.unpack_from(data)
    if magic != _MAGIC or not name_len or not 0 < seq < 2**63:
        raise SecurityError("invalid envelope")
    if payload_len < _GCM_TAG_SIZE or len(data) != (
        _HEADER.size + name_len + _NONCE_SIZE + payload_len + _TAG_SIZE
    ):
        raise SecurityError("invalid envelope length")
    try:
        sender = data[_HEADER.size : _HEADER.size + name_len].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecurityError("invalid sender") from exc
    key = keys.get(sender)
    if (
        key is None
        or len(key) < 32
        or not hmac.compare_digest(hmac.digest(key, data[:-_TAG_SIZE], "sha256"), data[-_TAG_SIZE:])
    ):
        raise SecurityError("authentication failed")
    current = int(time.time() * 1000) if now_ms is None else now_ms
    if abs(current - timestamp) > window_ms:
        raise SecurityError("timestamp outside acceptance window")
    body_start = _HEADER.size + name_len
    nonce = data[body_start : body_start + _NONCE_SIZE]
    ciphertext = data[body_start + _NONCE_SIZE : -_TAG_SIZE]
    encryption_key = hmac.digest(key, _ENCRYPTION_LABEL, "sha256")
    try:
        payload = AESGCM(encryption_key).decrypt(nonce, ciphertext, data[:body_start])
    except InvalidTag as exc:
        raise SecurityError("decryption failed") from exc
    return kind, sender, seq, payload


class SequenceStore:
    """SQLite-backed counters; atomic transactions serialize competing processes."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS sequences "
                "(name TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            )

    def next(self, name: str) -> int:
        with sqlite3.connect(self.path, isolation_level="IMMEDIATE") as db:
            db.execute(
                "INSERT INTO sequences VALUES (?, 1) ON CONFLICT(name) DO UPDATE SET value=value+1",
                (name,),
            )
            result = db.execute("SELECT value FROM sequences WHERE name=?", (name,)).fetchone()
            assert result is not None
            return int(result[0])

    def accept(self, name: str, sequence: int) -> bool:
        if not 0 < sequence < 2**63:
            return False
        with sqlite3.connect(self.path, isolation_level="IMMEDIATE") as db:
            result = db.execute(
                "INSERT INTO sequences VALUES (?, ?) ON CONFLICT(name) DO UPDATE "
                "SET value=excluded.value WHERE excluded.value > value",
                (name, sequence),
            )
            return result.rowcount == 1


class DatagramSecurity:
    """Authenticated datagram sender and receiver for one local identity."""

    DISCOVERY = 1
    ANNOUNCEMENT = 2
    TELEMETRY = 3

    def __init__(self, identity: str, key_dir: Path, state_path: Path) -> None:
        if not identity or Path(identity).name != identity or identity in {".", ".."}:
            raise ValueError("invalid security identity")
        self.identity = identity
        self.key_dir = key_dir
        state_path.parent.mkdir(parents=True, exist_ok=True)
        self.sequences = SequenceStore(state_path)
        self._key(identity)  # Fail closed if the local identity has no provisioned key.

    def _key(self, identity: str) -> bytes:
        if not identity or Path(identity).name != identity or identity in {".", ".."}:
            raise SecurityError("invalid sender identity")
        try:
            key = (self.key_dir / (identity + ".key")).read_bytes()
        except OSError as exc:
            raise SecurityError("unknown sender identity") from exc
        if len(key) != 32:
            raise SecurityError("invalid HMAC key")
        return key

    def encode(self, kind: int, payload: bytes) -> bytes:
        sequence = self.sequences.next("out:" + self.identity)
        return seal(
            kind,
            self.identity,
            sequence,
            int(time.time() * 1000),
            payload,
            self._key(self.identity),
        )

    def decode(self, data: bytes, *, expected_sender: str | None = None) -> tuple[int, str, bytes]:
        if len(data) < _HEADER.size + _TAG_SIZE:
            raise SecurityError("truncated envelope")
        _, _, name_len, _, _, _ = _HEADER.unpack_from(data)
        try:
            sender = data[_HEADER.size : _HEADER.size + name_len].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecurityError("invalid sender") from exc
        if expected_sender is not None and sender != expected_sender:
            raise SecurityError("unexpected sender")
        kind, sender, sequence, payload = open_envelope(data, {sender: self._key(sender)})
        if not self.sequences.accept("in:" + sender, sequence):
            raise SecurityError("replay detected")
        return kind, sender, payload


def datagram_security(identity: str) -> DatagramSecurity | None:
    """Return a secure-mode context using separately persisted replay state."""
    from common.tls import secure_mode

    if not secure_mode():
        return None
    base = Path(os.environ.get("DATAMESH_CREDENTIALS_DIR", ".datamesh-security"))
    state_dir = Path(os.environ.get("DATAMESH_SECURITY_STATE_DIR", ".datamesh-security-state"))
    return DatagramSecurity(identity, base / "hmac", state_dir / (identity + ".sqlite3"))
