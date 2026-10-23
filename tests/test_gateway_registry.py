import datamesh_pb2
import pytest

from gateway.registry import OFFLINE_THRESHOLD_MS, DeviceRegistry


@pytest.fixture
def registry() -> DeviceRegistry:
    return DeviceRegistry()


def test_registers_and_retrieves_device_info(registry: DeviceRegistry) -> None:
    # Arrange
    device = datamesh_pb2.DeviceInfo(
        device_id="ac-rack-01",
        device_type=datamesh_pb2.AIR_CONDITIONER,
        ip="127.0.0.1",
        grpc_port=50051,
        is_online=True,
        state_summary="AC ON | Target: 21.0C | Fan: 80%",
        last_seen_ms=1000,
    )

    # Act
    registry.register_device(device)
    retrieved = registry.get_device("ac-rack-01", current_time_ms=1000)

    # Assert
    assert retrieved is not None
    assert retrieved.device_id == "ac-rack-01"
    assert retrieved.grpc_port == 50051
    assert retrieved.is_online is True


def test_updates_device_from_telemetry_packet(registry: DeviceRegistry) -> None:
    # Arrange
    initial_device = datamesh_pb2.DeviceInfo(
        device_id="temp-rack-01",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        ip="127.0.0.1",
        last_seen_ms=1000,
    )
    registry.register_device(initial_device)

    telemetry = datamesh_pb2.TelemetryPacket(
        device_id="temp-rack-01",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        timestamp_ms=2500,
        temperature_c=27.4,
    )

    # Act
    registry.update_from_telemetry(telemetry)
    updated = registry.get_device("temp-rack-01", current_time_ms=2500)

    # Assert
    assert updated is not None
    assert updated.last_seen_ms == 2500
    assert "27.4 °C" in updated.state_summary
    assert updated.is_online is True


def test_passive_failure_detection_marks_device_offline_after_threshold(
    registry: DeviceRegistry,
) -> None:
    # Arrange
    device = datamesh_pb2.DeviceInfo(
        device_id="pdu-rack-01",
        device_type=datamesh_pb2.RACK_PDU,
        ip="127.0.0.1",
        last_seen_ms=10000,
    )
    registry.register_device(device)

    # Act: Within 15s threshold -> ONLINE; Beyond 15s threshold -> OFFLINE
    online_check = registry.get_device("pdu-rack-01", current_time_ms=10000 + OFFLINE_THRESHOLD_MS)
    offline_check = registry.get_device(
        "pdu-rack-01", current_time_ms=10000 + OFFLINE_THRESHOLD_MS + 1
    )

    # Assert
    assert online_check is not None and online_check.is_online is True
    assert offline_check is not None and offline_check.is_online is False


def test_recovering_device_transitions_back_to_online(registry: DeviceRegistry) -> None:
    # Arrange: Device marked offline at time 30_000 (last seen at 10_000)
    device = datamesh_pb2.DeviceInfo(
        device_id="temp-rack-02",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        ip="127.0.0.1",
        last_seen_ms=10000,
    )
    registry.register_device(device)
    offline_dev = registry.get_device("temp-rack-02", current_time_ms=30000)
    assert offline_dev is not None and offline_dev.is_online is False

    # Act: Device recovers and sends a new telemetry packet at time 32_000
    telemetry = datamesh_pb2.TelemetryPacket(
        device_id="temp-rack-02",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        timestamp_ms=32000,
        temperature_c=24.5,
    )
    registry.update_from_telemetry(telemetry)
    recovered = registry.get_device("temp-rack-02", current_time_ms=32500)

    # Assert
    assert recovered is not None
    assert recovered.is_online is True
    assert recovered.last_seen_ms == 32000


def test_get_unknown_device_returns_none(registry: DeviceRegistry) -> None:
    # Act & Assert
    assert registry.get_device("unknown-device", current_time_ms=1000) is None
    assert registry.list_devices(current_time_ms=1000) == []


def test_updates_unseen_device_from_telemetry_creates_new_entry(
    registry: DeviceRegistry,
) -> None:
    # Arrange: Telemetry arrives for a device not previously registered
    telemetry = datamesh_pb2.TelemetryPacket(
        device_id="unseen-temp-01",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        timestamp_ms=5000,
        temperature_c=31.2,
        is_alert=True,
    )

    # Act
    registry.update_from_telemetry(telemetry)
    device = registry.get_device("unseen-temp-01", current_time_ms=5000)

    # Assert
    assert device is not None
    assert device.device_id == "unseen-temp-01"
    assert "31.2 °C [ALERTA]" in device.state_summary
    assert device.is_online is True


def test_builds_state_summaries_for_ac_and_pdu_types(registry: DeviceRegistry) -> None:
    # Arrange
    ac_packet = datamesh_pb2.TelemetryPacket(
        device_id="ac-01",
        device_type=datamesh_pb2.AIR_CONDITIONER,
        timestamp_ms=1000,
        ac_power_on=True,
        temperature_c=22.0,
        target_temp_c=20.0,
        fan_speed_pct=75,
    )
    pdu_packet = datamesh_pb2.TelemetryPacket(
        device_id="pdu-01",
        device_type=datamesh_pb2.RACK_PDU,
        timestamp_ms=1000,
        power_watts=1600.0,
        current_amps=7.3,
        voltage_volts=219.5,
    )

    # Act
    registry.update_from_telemetry(ac_packet)
    registry.update_from_telemetry(pdu_packet)
    ac_dev = registry.get_device("ac-01", current_time_ms=1000)
    pdu_dev = registry.get_device("pdu-01", current_time_ms=1000)

    # Assert
    assert ac_dev is not None and "AC ON | Temp: 22.0 °C" in ac_dev.state_summary
    assert pdu_dev is not None and "PDU 1600.0 W | 7.3 A | 219.5 V" in pdu_dev.state_summary


def test_default_timestamp_handling_when_omitted(registry: DeviceRegistry) -> None:
    # Arrange: device with last_seen_ms = 0
    device = datamesh_pb2.DeviceInfo(
        device_id="ac-auto",
        device_type=datamesh_pb2.AIR_CONDITIONER,
        last_seen_ms=0,
    )

    # Act
    registry.register_device(device)
    retrieved = registry.get_device("ac-auto")
    all_devices = registry.list_devices()

    # Telemetry with timestamp_ms = 0 should also default defensively
    zero_time_packet = datamesh_pb2.TelemetryPacket(
        device_id="ac-auto",
        device_type=datamesh_pb2.AIR_CONDITIONER,
        timestamp_ms=0,
    )
    registry.update_from_telemetry(zero_time_packet)
    updated = registry.get_device("ac-auto")

    # Assert
    assert retrieved is not None
    assert retrieved.last_seen_ms > 0
    assert retrieved.is_online is True
    assert len(all_devices) == 1
    assert updated is not None and updated.last_seen_ms > 0
    assert updated.is_online is True
