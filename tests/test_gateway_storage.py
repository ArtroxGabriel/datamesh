from collections.abc import Generator

import datamesh_pb2
import pytest

from gateway.storage import TelemetryStorage


@pytest.fixture
def storage() -> Generator[TelemetryStorage]:
    with TelemetryStorage(":memory:") as store:
        yield store


def test_record_and_retrieve_recent_history(storage: TelemetryStorage) -> None:
    # Arrange
    packet_1 = datamesh_pb2.TelemetryPacket(
        device_id="temp-rack-01",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        timestamp_ms=1000,
        temperature_c=25.0,
    )
    packet_2 = datamesh_pb2.TelemetryPacket(
        device_id="temp-rack-02",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        timestamp_ms=2000,
        temperature_c=28.5,
        is_alert=True,
    )

    # Act
    storage.record_telemetry(packet_1)
    storage.record_telemetry(packet_2)
    history = storage.get_recent_history(limit=10)

    # Assert
    assert len(history) == 2
    assert history[0].device_id == "temp-rack-01"
    assert history[1].device_id == "temp-rack-02"
    assert history[1].is_alert is True


def test_query_hottest_rack(storage: TelemetryStorage) -> None:
    # Arrange
    storage.record_telemetry(
        datamesh_pb2.TelemetryPacket(
            device_id="temp-rack-01",
            device_type=datamesh_pb2.TEMPERATURE_SENSOR,
            timestamp_ms=5000,
            temperature_c=31.0,
        )
    )
    storage.record_telemetry(
        datamesh_pb2.TelemetryPacket(
            device_id="temp-rack-02",
            device_type=datamesh_pb2.TEMPERATURE_SENSOR,
            timestamp_ms=6000,
            temperature_c=39.2,
            is_alert=True,
        )
    )

    # Act
    result = storage.query_hottest_rack(window_seconds=10, reference_time_ms=7000)

    # Assert
    assert result.query_type == datamesh_pb2.HOTTEST_RACK
    assert result.target_device_id == "temp-rack-02"
    assert abs(result.primary_value - 39.2) < 1e-4
    assert result.sample_count == 2
    assert "temp-rack-02" in result.summary


def test_query_average_pdu_power(storage: TelemetryStorage) -> None:
    # Arrange
    storage.record_telemetry(
        datamesh_pb2.TelemetryPacket(
            device_id="pdu-rack-01",
            device_type=datamesh_pb2.RACK_PDU,
            timestamp_ms=5000,
            power_watts=1200.0,
        )
    )
    storage.record_telemetry(
        datamesh_pb2.TelemetryPacket(
            device_id="pdu-rack-02",
            device_type=datamesh_pb2.RACK_PDU,
            timestamp_ms=6000,
            power_watts=1800.0,
        )
    )

    # Act
    result = storage.query_average_pdu_power(window_seconds=10, reference_time_ms=7000)

    # Assert
    assert result.query_type == datamesh_pb2.AVG_PDU_POWER
    assert abs(result.primary_value - 1500.0) < 1e-4
    assert result.sample_count == 2
    assert result.unit == "W"


def test_query_thermal_stability(storage: TelemetryStorage) -> None:
    # Arrange: temperatures 20.0 and 30.0 -> mean 25.0, population stddev 5.0
    storage.record_telemetry(
        datamesh_pb2.TelemetryPacket(
            device_id="temp-rack-01",
            device_type=datamesh_pb2.TEMPERATURE_SENSOR,
            timestamp_ms=5000,
            temperature_c=20.0,
        )
    )
    storage.record_telemetry(
        datamesh_pb2.TelemetryPacket(
            device_id="temp-rack-02",
            device_type=datamesh_pb2.TEMPERATURE_SENSOR,
            timestamp_ms=6000,
            temperature_c=30.0,
        )
    )

    # Act
    result = storage.query_thermal_stability(window_seconds=10, reference_time_ms=7000)

    # Assert
    assert result.query_type == datamesh_pb2.THERMAL_STABILITY
    assert abs(result.primary_value - 25.0) < 1e-4
    assert abs(result.secondary_value - 5.0) < 1e-4
    assert result.sample_count == 2
    assert result.unit == "°C"


def test_queries_empty_window_gracefully(storage: TelemetryStorage) -> None:
    # Act
    hottest = storage.query_hottest_rack(window_seconds=60, reference_time_ms=10000)
    avg_pdu = storage.query_average_pdu_power(window_seconds=60, reference_time_ms=10000)
    stability = storage.query_thermal_stability(window_seconds=60, reference_time_ms=10000)

    # Assert
    assert hottest.sample_count == 0
    assert hottest.primary_value == 0.0
    assert avg_pdu.sample_count == 0
    assert avg_pdu.primary_value == 0.0
    assert stability.sample_count == 0
    assert stability.primary_value == 0.0
    assert stability.secondary_value == 0.0


def test_queries_exclude_records_outside_time_window(storage: TelemetryStorage) -> None:
    # Arrange: reference is 20000ms, window is 10s (cutoff 10000ms).
    # Packet at 5000ms is expired; packet at 15000ms is included.
    expired = datamesh_pb2.TelemetryPacket(
        device_id="temp-old",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        timestamp_ms=5000,
        temperature_c=45.0,
    )
    recent = datamesh_pb2.TelemetryPacket(
        device_id="temp-recent",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        timestamp_ms=15000,
        temperature_c=25.0,
    )
    storage.record_telemetry(expired)
    storage.record_telemetry(recent)

    # Act
    hottest = storage.query_hottest_rack(window_seconds=10, reference_time_ms=20000)

    # Assert
    assert hottest.sample_count == 1
    assert hottest.target_device_id == "temp-recent"
    assert abs(hottest.primary_value - 25.0) < 1e-4


def test_sqlite_storage_and_analytics_components_directly() -> None:
    # Arrange
    from gateway.storage import AnalyticsEngine, SQLiteTelemetryStorage

    with SQLiteTelemetryStorage(":memory:") as raw_storage:
        raw_storage.record_telemetry(
            datamesh_pb2.TelemetryPacket(
                device_id="temp-01",
                device_type=datamesh_pb2.TEMPERATURE_SENSOR,
                timestamp_ms=1000,
                temperature_c=22.0,
            )
        )
        engine = AnalyticsEngine(raw_storage)

        # Act
        hottest = engine.query_hottest_rack(window_seconds=10, reference_time_ms=1500)
        history = raw_storage.get_recent_history(limit=5)

        # Assert
        assert len(history) == 1
        assert hottest.target_device_id == "temp-01"
        assert abs(hottest.primary_value - 22.0) < 1e-4
