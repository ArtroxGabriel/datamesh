"""Event timeline for the Web Client: derives connectivity and alert events from Gateway polling.

Events are detected in the client process (not in the browser) so the timeline covers the whole
demo even when the events page is opened later. The Gateway is still reached only over TCP.
"""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

import datamesh_pb2

logger = logging.getLogger(__name__)

MAX_EVENTS = 500
DEFAULT_POLL_INTERVAL_SEC = 1.0
# Covers well over one poll interval of telemetry from every demo source (~1.6 packets/s).
HISTORY_POLL_LIMIT = 200

CATEGORY_CONNECTIVITY = "connectivity"
CATEGORY_ALERT = "alert"
CATEGORY_ACTUATION = "actuation"
CATEGORY_ANALYTICS = "analytics"

SEVERITY_INFO = "info"
SEVERITY_SUCCESS = "success"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

DEVICE_TYPE_LABELS = {
    datamesh_pb2.AIR_CONDITIONER: "Ar-condicionado",
    datamesh_pb2.TEMPERATURE_SENSOR: "Sensor térmico",
    datamesh_pb2.RACK_PDU: "PDU de rack",
}

QUERY_LABELS = {
    datamesh_pb2.HOTTEST_RACK: "Rack mais quente",
    datamesh_pb2.AVG_PDU_POWER: "Potência média das PDUs",
    datamesh_pb2.THERMAL_STABILITY: "Estabilidade térmica",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class Event:
    """A single timeline entry shown on the events page."""

    timestamp_ms: int
    category: str
    severity: str
    device_id: str
    message: str


class EventTimeline:
    """Thread-safe event store plus the per-device state needed to detect transitions."""

    def __init__(
        self, max_events: int = MAX_EVENTS, clock: Callable[[], int] | None = None
    ) -> None:
        self._events: deque[Event] = deque(maxlen=max_events)
        self._clock: Callable[[], int] = clock or _now_ms
        self._lock = threading.Lock()
        self._online: dict[str, bool] = {}
        self._alerting: dict[str, bool] = {}
        self._last_packet_ms: dict[str, int] = {}

    def recent(self, limit: int = MAX_EVENTS) -> list[Event]:
        """Returns the newest events first.

        Example:
            events = timeline.recent(limit=50)
        """
        with self._lock:
            ordered = sorted(self._events, key=lambda e: e.timestamp_ms, reverse=True)
        return ordered[:limit]

    def _add(self, category: str, severity: str, device_id: str, message: str, ts_ms: int) -> None:
        with self._lock:
            self._events.append(Event(ts_ms, category, severity, device_id, message))

    def observe_devices(self, devices: Iterable[datamesh_pb2.DeviceInfo]) -> None:
        """Emits events for newly seen sources and ONLINE/OFFLINE transitions.

        Example:
            timeline.observe_devices(client.list_devices())
        """
        for device in devices:
            previous = self._online.get(device.device_id)
            self._online[device.device_id] = device.is_online
            if previous is None:
                self._on_new_device(device)
            elif previous != device.is_online:
                self._on_status_change(device)

    def _on_new_device(self, device: datamesh_pb2.DeviceInfo) -> None:
        label = DEVICE_TYPE_LABELS.get(device.device_type, "Fonte")
        status = "ONLINE" if device.is_online else "OFFLINE"
        severity = SEVERITY_INFO if device.is_online else SEVERITY_WARNING
        message = f"{label} registrado no Gateway ({status})"
        self._add(CATEGORY_CONNECTIVITY, severity, device.device_id, message, self._clock())

    def _on_status_change(self, device: datamesh_pb2.DeviceInfo) -> None:
        if device.is_online:
            severity, message = SEVERITY_SUCCESS, "Voltou a enviar telemetria (ONLINE)"
        else:
            severity, message = SEVERITY_WARNING, "Sem telemetria há mais de 15 s (OFFLINE)"
        self._add(CATEGORY_CONNECTIVITY, severity, device.device_id, message, self._clock())

    def observe_telemetry(self, history: Iterable[datamesh_pb2.TelemetryPacket]) -> None:
        """Emits alert start/end events from packets not seen in previous polls.

        Uses the packet's own is_alert flag and timestamp, so the event time is when the
        sensor fired, not when the client happened to poll.

        Example:
            timeline.observe_telemetry(client.get_history(limit=200))
        """
        for packet in history:
            if packet.timestamp_ms <= self._last_packet_ms.get(packet.device_id, 0):
                continue
            self._last_packet_ms[packet.device_id] = packet.timestamp_ms
            if packet.device_type == datamesh_pb2.TEMPERATURE_SENSOR:
                self._check_alert_transition(packet)

    def _check_alert_transition(self, packet: datamesh_pb2.TelemetryPacket) -> None:
        was_alerting = self._alerting.get(packet.device_id, False)
        self._alerting[packet.device_id] = packet.is_alert
        if packet.is_alert == was_alerting:
            return
        temp = packet.temperature_c
        if packet.is_alert:
            severity, message = SEVERITY_CRITICAL, f"ALERTA térmico: {temp:.1f} °C (limiar 35 °C)"
        else:
            severity, message = SEVERITY_SUCCESS, f"Alerta encerrado: {temp:.1f} °C"
        self._add(CATEGORY_ALERT, severity, packet.device_id, message, packet.timestamp_ms)

    def record_ac_command(
        self, command: datamesh_pb2.ACControlRequest, success: bool, detail: str
    ) -> None:
        """Logs an operator command sent to the AC through the Gateway (gRPC).

        Example:
            timeline.record_ac_command(request, success=True, detail="Success")
        """
        power = "ligar" if command.power_on else "desligar"
        message = (
            f"Comando gRPC: {power}, setpoint {command.target_temp_c:.1f} °C, "
            f"ventilação {command.fan_speed_pct}%"
        )
        if not success:
            message += f" — falhou: {detail}"
        severity = SEVERITY_INFO if success else SEVERITY_WARNING
        self._add(CATEGORY_ACTUATION, severity, command.device_id, message, self._clock())

    def record_analytics(self, result: datamesh_pb2.AnalyticsResult) -> None:
        """Logs an analytical query executed on the Gateway's SQLite history.

        Example:
            timeline.record_analytics(result)
        """
        # The Gateway summary already names the query; the label only covers an empty summary.
        detail = result.summary or QUERY_LABELS.get(result.query_type, "consulta analítica")
        message = f"Consulta executada: {detail} ({result.sample_count} amostras)"
        self._add(CATEGORY_ANALYTICS, SEVERITY_INFO, "gateway", message, self._clock())


class GatewayReader(Protocol):
    """The read-only slice of the Gateway client that the poller needs."""

    def list_devices(self) -> list[datamesh_pb2.DeviceInfo]: ...
    def get_history(self, limit: int = ...) -> list[datamesh_pb2.TelemetryPacket]: ...


class TimelinePoller:
    """Background thread feeding the timeline from the Gateway over TCP."""

    def __init__(
        self,
        client: GatewayReader,
        timeline: EventTimeline,
        interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    ) -> None:
        self._client = client
        self._timeline = timeline
        self._interval_sec = interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def poll_once(self) -> None:
        """Fetches devices and recent telemetry once and updates the timeline.

        Example:
            poller.poll_once()
        """
        self._timeline.observe_devices(self._client.list_devices())
        self._timeline.observe_telemetry(self._client.get_history(limit=HISTORY_POLL_LIMIT))

    def start(self) -> None:
        """Starts polling in a daemon thread until stop() is called.

        Example:
            poller.start()
        """
        self._thread = threading.Thread(target=self._run, daemon=True, name="event-timeline")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval_sec):
            try:
                self.poll_once()
            except Exception as err:
                logger.warning("Event timeline poll failed: %s", err)

    def stop(self) -> None:
        """Stops the polling thread.

        Example:
            poller.stop()
        """
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
