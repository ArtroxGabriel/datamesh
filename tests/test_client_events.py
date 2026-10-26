"""Unit tests for the Web Client event timeline."""

import datamesh_pb2
import pytest

from client.events import (
    CATEGORY_ACTUATION,
    CATEGORY_ALERT,
    CATEGORY_ANALYTICS,
    CATEGORY_CONNECTIVITY,
    SEVERITY_CRITICAL,
    SEVERITY_SUCCESS,
    SEVERITY_WARNING,
    EventTimeline,
    TimelinePoller,
)

NOW_MS = 1_700_000_000_000


@pytest.fixture
def timeline() -> EventTimeline:
    return EventTimeline(clock=lambda: NOW_MS)


def _device(device_id: str, is_online: bool = True) -> datamesh_pb2.DeviceInfo:
    return datamesh_pb2.DeviceInfo(
        device_id=device_id,
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        is_online=is_online,
    )


def _reading(ts_ms: int, temp_c: float, is_alert: bool) -> datamesh_pb2.TelemetryPacket:
    return datamesh_pb2.TelemetryPacket(
        device_id="temp-01",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        timestamp_ms=ts_ms,
        temperature=datamesh_pb2.TemperatureTelemetry(temperature_c=temp_c),
        is_alert=is_alert,
    )


def test_new_device_emits_registration_event_once(timeline: EventTimeline) -> None:
    # Act: same device observed in two consecutive polls
    timeline.observe_devices([_device("temp-01")])
    timeline.observe_devices([_device("temp-01")])

    # Assert
    events = timeline.recent()
    assert len(events) == 1
    assert events[0].category == CATEGORY_CONNECTIVITY
    assert events[0].device_id == "temp-01"
    assert "registrado" in events[0].message


def test_offline_and_recovery_transitions_emit_events(timeline: EventTimeline) -> None:
    # Arrange
    timeline.observe_devices([_device("pdu-01")])

    # Act
    timeline.observe_devices([_device("pdu-01", is_online=False)])
    timeline.observe_devices([_device("pdu-01", is_online=True)])

    # Assert: registration + OFFLINE + ONLINE
    severities = [e.severity for e in timeline.recent()]
    assert sorted(severities) == sorted(["info", SEVERITY_WARNING, SEVERITY_SUCCESS])


def test_device_missing_from_poll_is_not_treated_as_offline(timeline: EventTimeline) -> None:
    # Arrange: the TCP client returns [] when the Gateway is unreachable
    timeline.observe_devices([_device("temp-01")])

    # Act
    timeline.observe_devices([])

    # Assert: only the registration event
    assert len(timeline.recent()) == 1


def test_alert_start_and_end_use_packet_timestamps(timeline: EventTimeline) -> None:
    # Act
    timeline.observe_telemetry(
        [
            _reading(NOW_MS + 1_000, 24.0, is_alert=False),
            _reading(NOW_MS + 2_000, 38.8, is_alert=True),
            _reading(NOW_MS + 3_000, 38.5, is_alert=True),
            _reading(NOW_MS + 4_000, 32.0, is_alert=False),
        ]
    )

    # Assert: newest first
    end, start = timeline.recent()
    assert start.category == CATEGORY_ALERT
    assert start.severity == SEVERITY_CRITICAL
    assert start.timestamp_ms == NOW_MS + 2_000
    assert "38.8" in start.message
    assert end.severity == SEVERITY_SUCCESS
    assert end.timestamp_ms == NOW_MS + 4_000


def test_already_processed_packets_are_ignored_on_next_poll(timeline: EventTimeline) -> None:
    # Arrange: the history window overlaps between polls
    first_poll = [_reading(NOW_MS + 1_000, 38.8, is_alert=True)]
    timeline.observe_telemetry(first_poll)

    # Act
    timeline.observe_telemetry(first_poll + [_reading(NOW_MS + 2_000, 38.6, is_alert=True)])

    # Assert: a single alert-start event
    assert len(timeline.recent()) == 1


def test_ac_command_and_analytics_are_recorded(timeline: EventTimeline) -> None:
    # Arrange
    command = datamesh_pb2.ACControlRequest(
        device_id="ac-01", power_on=True, target_temp_c=19.5, fan_speed_pct=85
    )
    result = datamesh_pb2.AnalyticsResult(
        query_type=datamesh_pb2.HOTTEST_RACK, summary="temp-02 com pico de 38.8 °C", sample_count=42
    )

    # Act
    timeline.record_ac_command(command, success=False, detail="AC unreachable")
    timeline.record_analytics(result)

    # Assert
    categories = {e.category: e for e in timeline.recent()}
    actuation = categories[CATEGORY_ACTUATION]
    assert actuation.severity == SEVERITY_WARNING
    assert "19.5 °C" in actuation.message
    assert "AC unreachable" in actuation.message
    assert "temp-02 com pico de 38.8 °C (42 amostras)" in categories[CATEGORY_ANALYTICS].message


def test_recent_respects_limit_and_capacity() -> None:
    # Arrange
    timeline = EventTimeline(max_events=3, clock=lambda: NOW_MS)

    # Act
    timeline.observe_devices([_device(f"temp-{i}") for i in range(5)])

    # Assert: oldest entries dropped, limit applied on read
    assert len(timeline.recent()) == 3
    assert len(timeline.recent(limit=2)) == 2


class _FakeClient:
    def __init__(self) -> None:
        self.history_limits: list[int] = []

    def list_devices(self) -> list[datamesh_pb2.DeviceInfo]:
        return [_device("temp-01")]

    def get_history(self, limit: int = 100) -> list[datamesh_pb2.TelemetryPacket]:
        self.history_limits.append(limit)
        return [_reading(NOW_MS, 38.8, is_alert=True)]


def test_poller_feeds_devices_and_telemetry_into_timeline(timeline: EventTimeline) -> None:
    # Arrange
    client = _FakeClient()
    poller = TimelinePoller(client, timeline)

    # Act
    poller.poll_once()

    # Assert
    categories = sorted(e.category for e in timeline.recent())
    assert categories == [CATEGORY_ALERT, CATEGORY_CONNECTIVITY]
    assert client.history_limits == [200]
