import pytest

from common.security import SecurityError, SequenceStore, open_envelope, seal

KEY = b"k" * 32


def test_authenticated_envelope_and_tampering():
    packet = seal(2, "sensor-1", 7, 10000, b"readable telemetry", KEY)
    assert b"readable telemetry" not in packet
    assert open_envelope(packet, {"sensor-1": KEY}, now_ms=10000) == (
        2,
        "sensor-1",
        7,
        b"readable telemetry",
    )
    with pytest.raises(SecurityError):
        open_envelope(packet[:-33] + b"X" + packet[-32:], {"sensor-1": KEY}, now_ms=10000)
    with pytest.raises(SecurityError):
        open_envelope(packet, {"sensor-1": KEY}, now_ms=15001)
    with pytest.raises(SecurityError):
        open_envelope(packet, {}, now_ms=10000)


def test_sequence_persists_and_rejects_replay(tmp_path):
    path = tmp_path / "sequences.db"
    assert SequenceStore(path).next("source") == 1
    assert SequenceStore(path).next("source") == 2
    assert SequenceStore(path).accept("gateway:source", 2)
    assert not SequenceStore(path).accept("gateway:source", 2)
    assert not SequenceStore(path).accept("gateway:source", 1)
    assert SequenceStore(path).accept("gateway:source", 3)


def test_datagram_security_rejects_replay_and_wrong_identity(tmp_path):
    from common.security import DatagramSecurity

    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "gateway.key").write_bytes(b"g" * 32)
    (keys / "sensor.key").write_bytes(KEY)
    sensor = DatagramSecurity("sensor", keys, tmp_path / "sensor.db")
    gateway = DatagramSecurity("gateway", keys, tmp_path / "gateway.db")
    packet = sensor.encode(DatagramSecurity.TELEMETRY, b"reading")
    assert gateway.decode(packet) == (DatagramSecurity.TELEMETRY, "sensor", b"reading")
    gateway = DatagramSecurity("gateway", keys, tmp_path / "gateway.db")
    with pytest.raises(SecurityError, match="replay"):
        gateway.decode(packet)
    with pytest.raises(SecurityError, match="unexpected sender"):
        gateway.decode(
            sensor.encode(DatagramSecurity.TELEMETRY, b"other"), expected_sender="gateway"
        )


def test_encrypted_payload_nonce_and_integrity():
    import hmac

    first = seal(3, "sensor-1", 1, 10000, b"sensitive reading", KEY)
    second = seal(3, "sensor-1", 1, 10000, b"sensitive reading", KEY)
    assert first != second
    assert b"sensitive reading" not in first
    assert open_envelope(first, {"sensor-1": KEY}, now_ms=10000)[-1] == b"sensitive reading"
    modified = bytearray(first)
    modified[-33] ^= 1
    with pytest.raises(SecurityError, match="authentication"):
        open_envelope(bytes(modified), {"sensor-1": KEY}, now_ms=10000)
    # Even a valid outer MAC cannot make an altered AES-GCM tag valid.
    modified[-32:] = hmac.digest(KEY, modified[:-32], "sha256")
    with pytest.raises(SecurityError, match="decryption"):
        open_envelope(bytes(modified), {"sensor-1": KEY}, now_ms=10000)
    with pytest.raises(SecurityError):
        open_envelope(b"DMS1" + first[4:], {"sensor-1": KEY}, now_ms=10000)
