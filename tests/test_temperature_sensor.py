import socket

import datamesh_pb2
import pytest

from sources.temperature.sensor import (
    ALERT_CLEAR_TEMP_C,
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


class FakeClock:
    """Manually advanced monotonic clock so anomaly timing is tested without sleeping."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_socket() -> FakeUDPSocket:
    return FakeUDPSocket()


@pytest.fixture
def anomaly_sensor(fake_socket: FakeUDPSocket) -> tuple[TemperatureSensor, FakeClock]:
    clock = FakeClock()
    sensor = TemperatureSensor(
        device_id="temp-anomaly",
        gateway_host="127.0.0.1",
        gateway_port=9998,
        base_temp_c=26.0,
        socket_factory=lambda: fake_socket,
        anomaly_hold_sec=20.0,
        anomaly_decay_sec=10.0,
        clock=clock,
    )
    return sensor, clock


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
    assert abs(packet.temperature.temperature_c - 24.5) < 1e-4
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
    assert alert_packet.temperature.temperature_c >= ALERT_THRESHOLD_TEMP_C
    assert len(fake_socket.sent_packets) == 1

    raw_data, target = fake_socket.sent_packets[0]
    assert target == ("127.0.0.1", 9998)

    dispatched = datamesh_pb2.TelemetryPacket()
    dispatched.ParseFromString(raw_data)
    assert dispatched.device_id == "temp-rack-01"
    assert dispatched.is_alert is True
    assert abs(dispatched.temperature.temperature_c - 39.5) < 1e-4


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
    assert 20.0 <= reading.temperature.temperature_c <= 30.0
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
    monkeypatch.setenv("BASE_TEMP_C", "27.5")

    # Act
    cfg = _load_config()

    # Assert
    assert cfg[0] == "temp-rack-99"
    assert cfg[1] == "10.0.0.1"
    assert cfg[2] == 9900
    assert abs(cfg[3] - 1.5) < 1e-4
    assert cfg[4] == "239.255.0.3"
    assert cfg[5] == 9991
    assert abs(cfg[6] - 27.5) < 1e-4

    sensor = TemperatureSensor(device_id="temp-rack-99")
    stop_event = threading.Event()
    _setup_signals(sensor, stop_event, "temp-rack-99")


def test_custom_base_temp_and_sigusr1_anomaly_trigger(fake_socket: FakeUDPSocket) -> None:
    import signal
    import threading

    from sources.temperature.main import _setup_signals

    sensor = TemperatureSensor(
        device_id="temp-rack-02",
        gateway_host="127.0.0.1",
        gateway_port=9998,
        base_temp_c=28.0,
        socket_factory=lambda: fake_socket,
    )
    reading = sensor.create_reading()
    assert 26.5 <= reading.temperature.temperature_c <= 30.5

    stop_event = threading.Event()
    _setup_signals(sensor, stop_event, "temp-rack-02")

    # Act: send SIGUSR1 to trigger anomaly
    signal.raise_signal(signal.SIGUSR1)

    # Assert: immediate anomaly packet (> 35 C) was sent to Gateway
    assert len(fake_socket.sent_packets) == 1
    dispatched = datamesh_pb2.TelemetryPacket()
    dispatched.ParseFromString(fake_socket.sent_packets[0][0])
    assert dispatched.device_id == "temp-rack-02"
    assert dispatched.is_alert is True
    assert dispatched.temperature.temperature_c >= ALERT_THRESHOLD_TEMP_C

    # Readings inside the hold window stay in anomaly state (> 35 C) so dashboard shows alert
    next_reading = sensor.create_reading()
    assert next_reading.is_alert is True
    assert next_reading.temperature.temperature_c >= ALERT_THRESHOLD_TEMP_C


def test_start_multicast_listener_before_start_keeps_listener_thread_alive() -> None:
    # Arrange: get a free port to bind multicast listener
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("", 0))
        free_port = s.getsockname()[1]

    sensor = TemperatureSensor(
        device_id="temp-mcast-order",
        multicast_port=free_port,
        send_interval_sec=0.5,
    )
    try:
        # Act: call start_multicast_listener() BEFORE start(), matching sources/temperature/main.py
        sensor.start_multicast_listener()
        sensor.start()

        # Assert: multicast listener thread must still be alive
        assert sensor._mcast_thread is not None
        assert sensor._mcast_thread.is_alive() is True
    finally:
        sensor.stop()


def test_anomaly_stays_hot_during_hold_window(
    anomaly_sensor: tuple[TemperatureSensor, FakeClock],
) -> None:
    # Arrange
    sensor, clock = anomaly_sensor
    sensor.trigger_anomaly(temp_c=38.8)

    # Act: just before the hold window ends
    clock.advance(19.0)
    reading = sensor.create_reading()

    # Assert
    assert reading.is_alert is True
    assert reading.temperature.temperature_c >= ALERT_THRESHOLD_TEMP_C


def test_anomaly_cools_down_and_clears_alert_after_hold(
    anomaly_sensor: tuple[TemperatureSensor, FakeClock],
) -> None:
    # Arrange
    sensor, clock = anomaly_sensor
    sensor.trigger_anomaly(temp_c=38.8)

    # Act: one decay constant after the hold (excess 12.8 °C * e^-1 ≈ 4.7 °C)
    clock.advance(30.0)
    reading = sensor.create_reading()

    # Assert: still warmer than base, but below the clear threshold, so the alert is off
    assert 26.0 + 3.0 < reading.temperature.temperature_c < ALERT_CLEAR_TEMP_C
    assert reading.is_alert is False


def test_anomaly_settles_back_to_nominal_readings(
    anomaly_sensor: tuple[TemperatureSensor, FakeClock],
) -> None:
    # Arrange
    sensor, clock = anomaly_sensor
    sensor.trigger_anomaly(temp_c=38.8)

    # Act
    clock.advance(120.0)
    reading = sensor.create_reading()

    # Assert: anomaly state is discarded and readings fall back to the base noise band
    assert sensor._anomaly is None
    assert 26.0 - 1.5 <= reading.temperature.temperature_c <= 26.0 + 2.5
    assert reading.is_alert is False


def test_alert_uses_hysteresis_near_threshold(
    anomaly_sensor: tuple[TemperatureSensor, FakeClock],
) -> None:
    # Arrange
    sensor, _ = anomaly_sensor

    # Act & Assert: 34 °C keeps an active alert; only below 33 °C it clears
    assert sensor.create_reading(temp_c=36.0).is_alert is True
    assert sensor.create_reading(temp_c=34.0).is_alert is True
    assert sensor.create_reading(temp_c=32.9).is_alert is False
    assert sensor.create_reading(temp_c=34.0).is_alert is False


def test_retrigger_during_cooling_restarts_hold_window(
    anomaly_sensor: tuple[TemperatureSensor, FakeClock],
) -> None:
    # Arrange
    sensor, clock = anomaly_sensor
    sensor.trigger_anomaly(temp_c=38.8)
    clock.advance(30.0)

    # Act
    sensor.trigger_anomaly(temp_c=38.8)
    clock.advance(15.0)
    reading = sensor.create_reading()

    # Assert
    assert reading.is_alert is True
    assert reading.temperature.temperature_c >= ALERT_THRESHOLD_TEMP_C


def test_temperature_main_loads_anomaly_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    from sources.temperature.main import _load_anomaly_timing

    monkeypatch.setenv("ANOMALY_HOLD_SEC", "45")
    monkeypatch.setenv("ANOMALY_DECAY_SEC", "7.5")

    assert _load_anomaly_timing() == (45.0, 7.5)


def test_temperature_main_waits_for_discovery_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    from sources.temperature.main import _load_config

    monkeypatch.delenv("GATEWAY_HOST", raising=False)

    # Act
    cfg = _load_config()

    # Assert
    assert cfg[1] is None
