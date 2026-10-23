import socket

import datamesh_pb2
import pytest

from sources.temperature.sensor import (
    ALERT_THRESHOLD_TEMP_C,
    TemperatureSensor,
)


class FakeUDPSocket:
    """In-memory UDP socket fake to capture transmitted datagrams."""

    def __init__(self) -> None:
        self.sent_packets: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, data: bytes, target: tuple[str, int], /) -> int:
        self.sent_packets.append((data, target))
        return len(data)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_socket() -> FakeUDPSocket:
    return FakeUDPSocket()


def test_creates_periodic_telemetry_packet(fake_socket: FakeUDPSocket) -> None:
    # Arrange
    sensor = TemperatureSensor(
        device_id="temp-rack-01",
        gateway_host="127.0.0.1",
        gateway_port=9998,
        socket_factory=lambda: fake_socket,
    )

    # Act
    packet = sensor.create_reading(temp_c=24.5)

    # Assert
    assert packet.device_id == "temp-rack-01"
    assert packet.device_type == datamesh_pb2.TEMPERATURE_SENSOR
    assert packet.is_alert is False
    assert abs(packet.temperature_c - 24.5) < 1e-4
    assert packet.timestamp_ms > 0


def test_trigger_anomaly_sends_immediate_alert_packet(
    fake_socket: FakeUDPSocket,
) -> None:
    # Arrange
    sensor = TemperatureSensor(
        device_id="temp-rack-01",
        gateway_host="127.0.0.1",
        gateway_port=9998,
        socket_factory=lambda: fake_socket,
    )

    # Act: Trigger immediate anomaly (> 35.0 C)
    alert_packet = sensor.trigger_anomaly(temp_c=39.5)

    # Assert
    assert alert_packet.is_alert is True
    assert alert_packet.temperature_c >= ALERT_THRESHOLD_TEMP_C
    assert len(fake_socket.sent_packets) == 1

    raw_data, target = fake_socket.sent_packets[0]
    assert target == ("127.0.0.1", 9998)

    dispatched = datamesh_pb2.TelemetryPacket()
    dispatched.ParseFromString(raw_data)
    assert dispatched.device_id == "temp-rack-01"
    assert dispatched.is_alert is True
    assert abs(dispatched.temperature_c - 39.5) < 1e-4


def test_handles_multicast_discovery_beacon(fake_socket: FakeUDPSocket) -> None:
    # Arrange
    sensor = TemperatureSensor(
        device_id="temp-rack-01",
        socket_factory=lambda: fake_socket,
    )
    beacon = datamesh_pb2.DiscoveryRequest(
        gateway_ip="192.168.1.10",
        telemetry_udp_port=9998,
    )

    # Act: Process discovery request
    sensor.handle_discovery_request(beacon.SerializeToString())

    # Assert: Target was learned and DeviceInfo announcement sent back
    assert sensor.gateway_host == "192.168.1.10"
    assert sensor.gateway_port == 9998
    assert len(fake_socket.sent_packets) == 1

    raw_announcement, target = fake_socket.sent_packets[0]
    assert target == ("192.168.1.10", 9998)

    device_info = datamesh_pb2.DeviceInfo()
    device_info.ParseFromString(raw_announcement)
    assert device_info.device_id == "temp-rack-01"
    assert device_info.device_type == datamesh_pb2.TEMPERATURE_SENSOR


def test_temperature_simulation_bounded_within_expected_range() -> None:
    # Arrange
    sensor = TemperatureSensor(device_id="temp-sim")

    # Act
    reading = sensor.create_reading()

    # Assert: Simulated base temp should be within 20°C - 30°C
    assert 20.0 <= reading.temperature_c <= 30.0
    assert reading.is_alert is False


def test_handles_corrupt_discovery_beacon_gracefully(fake_socket: FakeUDPSocket) -> None:
    # Arrange
    sensor = TemperatureSensor(
        device_id="temp-corrupt",
        socket_factory=lambda: fake_socket,
    )

    # Act: Corrupted byte string
    sensor.handle_discovery_request(b"\xff\xff\xff\xff\x00")

    # Assert: Should not crash, and no packets sent
    assert len(fake_socket.sent_packets) == 0


def test_send_telemetry_without_target_does_nothing(fake_socket: FakeUDPSocket) -> None:
    # Arrange: Sensor without gateway_host or gateway_port
    sensor = TemperatureSensor(
        device_id="temp-no-gw",
        socket_factory=lambda: fake_socket,
    )
    reading = sensor.create_reading(temp_c=25.0)

    # Act
    sensor.send_telemetry(reading)

    # Assert: No crash, nothing sent
    assert len(fake_socket.sent_packets) == 0


def test_multicast_listener_bind_failure_handled(
    monkeypatch: pytest.MonkeyPatch, fake_socket: FakeUDPSocket
) -> None:
    # Arrange: Simulate environment where multicast bind fails (e.g. permission or port conflict)
    sensor = TemperatureSensor(
        device_id="temp-mcast-fail",
        socket_factory=lambda: fake_socket,
    )

    def _fail_bind(*args: object, **kwargs: object) -> None:
        raise OSError("Permission denied")

    monkeypatch.setattr(socket.socket, "bind", _fail_bind)

    # Act & Assert: Should log warning and not raise
    sensor.start_multicast_listener()
    assert sensor._mcast_sock is None


def test_sensor_lifecycle_runs_and_stops_cleanly(fake_socket: FakeUDPSocket) -> None:
    # Arrange
    sensor = TemperatureSensor(
        device_id="temp-rack-01",
        gateway_host="127.0.0.1",
        gateway_port=9998,
        send_interval_sec=0.01,
        socket_factory=lambda: fake_socket,
    )

    # Act
    sensor.start()
    import time

    time.sleep(0.05)
    sensor.stop()

    # Assert: Telemetry packets were sent periodically in the background
    assert len(fake_socket.sent_packets) >= 2
    assert fake_socket.closed is True


def test_temperature_multicast_listener_bind_fallback() -> None:
    # Arrange: invalid port causes bind failure
    sensor = TemperatureSensor(
        device_id="temp-rack-01",
        multicast_port=-99,
    )

    # Act & Assert
    sensor.start_multicast_listener()
    assert sensor._mcast_sock is None


def test_temperature_main_load_config_and_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    import threading

    from sources.temperature.main import _load_config, _setup_signals

    monkeypatch.setenv("SENSOR_ID", "temp-rack-99")
    monkeypatch.setenv("GATEWAY_HOST", "10.0.0.1")
    monkeypatch.setenv("GATEWAY_PORT", "9900")
    monkeypatch.setenv("SEND_INTERVAL_SEC", "1.5")
    monkeypatch.setenv("MULTICAST_GROUP", "239.255.0.3")
    monkeypatch.setenv("MULTICAST_PORT", "9991")

    # Act
    cfg = _load_config()

    # Assert
    assert cfg[0] == "temp-rack-99"
    assert cfg[1] == "10.0.0.1"
    assert cfg[2] == 9900
    assert abs(cfg[3] - 1.5) < 1e-4
    assert cfg[4] == "239.255.0.3"
    assert cfg[5] == 9991

    sensor = TemperatureSensor(device_id="temp-rack-99")
    stop_event = threading.Event()
    _setup_signals(sensor, stop_event, "temp-rack-99")
