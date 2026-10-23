"""In-memory device registry with passive offline failure detection for DataMesh Gateway."""

import threading
import time

import datamesh_pb2

OFFLINE_THRESHOLD_MS = 15_000


def _now_ms() -> int:
    return int(time.time() * 1000)


def _build_state_summary(packet: datamesh_pb2.TelemetryPacket) -> str:
    if packet.device_type == datamesh_pb2.AIR_CONDITIONER:
        status = "ON" if packet.ac_power_on else "OFF"
        return (
            f"AC {status} | Temp: {packet.temperature_c:.1f} °C | "
            f"Setpoint: {packet.target_temp_c:.1f} °C | Fan: {packet.fan_speed_pct}%"
        )
    if packet.device_type == datamesh_pb2.RACK_PDU:
        return (
            f"PDU {packet.power_watts:.1f} W | "
            f"{packet.current_amps:.1f} A | {packet.voltage_volts:.1f} V"
        )
    alert = " [ALERTA]" if packet.is_alert else ""
    return f"Temp: {packet.temperature_c:.1f} °C{alert}"


class DeviceRegistry:
    """Thread-safe registry of connected data sources with passive failure tracking."""

    def __init__(self) -> None:
        self._devices: dict[str, datamesh_pb2.DeviceInfo] = {}
        self._lock = threading.Lock()

    def register_device(self, info: datamesh_pb2.DeviceInfo) -> None:
        """Registers or updates a discovered device in the registry.

        Example:
            registry.register_device(device_info)
        """
        device_copy = datamesh_pb2.DeviceInfo()
        device_copy.CopyFrom(info)
        if device_copy.last_seen_ms == 0:
            device_copy.last_seen_ms = _now_ms()

        with self._lock:
            self._devices[device_copy.device_id] = device_copy

    def update_from_telemetry(self, packet: datamesh_pb2.TelemetryPacket) -> None:
        """Updates device timestamp and summary from periodic or alert telemetry.

        Example:
            registry.update_from_telemetry(packet)
        """
        with self._lock:
            existing = self._devices.get(packet.device_id)
            if existing is None:
                existing = datamesh_pb2.DeviceInfo(
                    device_id=packet.device_id,
                    device_type=packet.device_type,
                )
                self._devices[packet.device_id] = existing

            existing.last_seen_ms = packet.timestamp_ms if packet.timestamp_ms > 0 else _now_ms()
            existing.device_type = packet.device_type
            existing.state_summary = _build_state_summary(packet)

    def _clone_with_status(
        self, device: datamesh_pb2.DeviceInfo, now_ms: int
    ) -> datamesh_pb2.DeviceInfo:
        clone = datamesh_pb2.DeviceInfo()
        clone.CopyFrom(device)
        clone.is_online = (now_ms - device.last_seen_ms) <= OFFLINE_THRESHOLD_MS
        return clone

    def get_device(
        self, device_id: str, current_time_ms: int | None = None
    ) -> datamesh_pb2.DeviceInfo | None:
        """Retrieves a single device by ID with dynamically computed online status.

        Example:
            device = registry.get_device("temp-rack-01")
        """
        now_ms = current_time_ms if current_time_ms is not None else _now_ms()
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                return None
            return self._clone_with_status(device, now_ms)

    def list_devices(self, current_time_ms: int | None = None) -> list[datamesh_pb2.DeviceInfo]:
        """Lists all registered devices with dynamically evaluated online statuses.

        Example:
            devices = registry.list_devices()
        """
        now_ms = current_time_ms if current_time_ms is not None else _now_ms()
        with self._lock:
            return [self._clone_with_status(device, now_ms) for device in self._devices.values()]
