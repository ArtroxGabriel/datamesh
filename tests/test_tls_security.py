import subprocess
from pathlib import Path

import pytest

from common.tls import (
    client_context,
    grpc_gateway_credentials,
    grpc_server_credentials,
    server_context,
)
from gateway.main import GatewayApp


def test_generated_credentials_load_and_cannot_be_overwritten(tmp_path, monkeypatch):
    credentials = tmp_path / "credentials"
    monkeypatch.setenv("DATAMESH_CREDENTIALS_DIR", str(credentials))
    script = Path(__file__).resolve().parents[1] / "scripts/security/generate_credentials.sh"
    subprocess.run([str(script)], check=True, capture_output=True)
    assert client_context().check_hostname
    assert server_context().verify_mode
    assert grpc_server_credentials()
    assert grpc_gateway_credentials()
    assert subprocess.run([str(script)], capture_output=True).returncode != 0


def test_gateway_secure_mode_requires_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAMESH_SECURITY_MODE", "secure")
    monkeypatch.setenv("DATAMESH_CREDENTIALS_DIR", str(tmp_path / "missing"))
    with pytest.raises((FileNotFoundError, OSError)):
        GatewayApp(db_path=str(tmp_path / "gateway.db"))


def test_secure_sensor_telemetry_rejects_replay(tmp_path, monkeypatch, caplog):
    import datamesh_pb2

    from gateway.service import GatewayCoordinator
    from gateway.storage import TelemetryStorage
    from sources.temperature.sensor import TemperatureSensor

    credentials = tmp_path / "credentials"
    monkeypatch.setenv("DATAMESH_CREDENTIALS_DIR", str(credentials))
    monkeypatch.setenv("DATAMESH_SECURITY_STATE_DIR", str(tmp_path / "state"))
    script = Path(__file__).resolve().parents[1] / "scripts/security/generate_credentials.sh"
    subprocess.run([str(script)], check=True, capture_output=True)
    (credentials / "hmac").mkdir()
    for name in ("gateway", "sensor"):
        (credentials / "hmac" / f"{name}.key").write_bytes(name.encode().ljust(32, b"!"))
    monkeypatch.setenv("DATAMESH_SECURITY_MODE", "secure")

    class Sender:
        packets = []

        def sendto(self, data, target):
            self.packets.append(data)
            return len(data)

        def close(self):
            pass

    sender = Sender()
    source = TemperatureSensor("sensor", "127.0.0.1", 9998, socket_factory=lambda: sender)
    gateway = GatewayCoordinator(storage=TelemetryStorage(":memory:"))
    try:
        source.send_telemetry(source.create_reading(temp_c=23))
        normal = sender.packets[-1]
        gateway.handle_udp_datagram(normal, ("127.0.0.1", 1234))
        source.trigger_anomaly(38)
        gateway.handle_udp_datagram(sender.packets[-1], ("127.0.0.1", 1234))
        gateway.handle_udp_datagram(normal, ("127.0.0.1", 1234))
        history = gateway.storage.get_recent_history(10)
        assert len(history) == 2
        assert any(item.temperature.temperature_c == 38 for item in history)
        assert "replay detected" in caplog.text
        forged = datamesh_pb2.TelemetryPacket(
            device_id="sensor", device_type=datamesh_pb2.TEMPERATURE_SENSOR, timestamp_ms=1
        )
        gateway.handle_udp_datagram(forged.SerializeToString(), ("127.0.0.1", 1234))
        assert len(gateway.storage.get_recent_history(10)) == 2
    finally:
        gateway.close()
