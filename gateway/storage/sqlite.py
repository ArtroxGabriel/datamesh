"""SQLite implementation of telemetry time-series storage."""

import sqlite3
import threading

import datamesh_pb2

from gateway.storage.queries import (
    INSERT_TELEMETRY_SQL,
    SCHEMA_DDL,
    SELECT_AVG_PDU_POWER_SQL,
    SELECT_HOTTEST_RACK_SQL,
    SELECT_RECENT_HISTORY_SQL,
    SELECT_THERMAL_STABILITY_SQL,
)


def _row_to_telemetry_packet(r: sqlite3.Row) -> datamesh_pb2.TelemetryPacket:
    dev_type = r["device_type"]
    dev_id = str(r["device_id"])
    ts_ms = int(r["timestamp_ms"])
    alert = bool(r["is_alert"])

    if dev_type == datamesh_pb2.TEMPERATURE_SENSOR:
        return datamesh_pb2.TelemetryPacket(
            device_id=dev_id,
            device_type=dev_type,
            timestamp_ms=ts_ms,
            is_alert=alert,
            temperature=datamesh_pb2.TemperatureTelemetry(
                temperature_c=float(r["temperature_c"] or 0.0)
            ),
        )
    if dev_type == datamesh_pb2.AIR_CONDITIONER:
        return datamesh_pb2.TelemetryPacket(
            device_id=dev_id,
            device_type=dev_type,
            timestamp_ms=ts_ms,
            is_alert=alert,
            ac=datamesh_pb2.ACTelemetry(
                temperature_c=float(r["temperature_c"] or 0.0),
                target_temp_c=float(r["target_temp_c"] or 0.0),
                fan_speed_pct=int(r["fan_speed_pct"] or 0),
                power_watts=float(r["power_watts"] or 0.0),
                current_amps=float(r["current_amps"] or 0.0),
                voltage_volts=float(r["voltage_volts"] or 0.0),
                ac_power_on=bool(r["ac_power_on"]),
            ),
        )
    if dev_type == datamesh_pb2.RACK_PDU:
        return datamesh_pb2.TelemetryPacket(
            device_id=dev_id,
            device_type=dev_type,
            timestamp_ms=ts_ms,
            is_alert=alert,
            pdu=datamesh_pb2.PDUTelemetry(
                power_watts=float(r["power_watts"] or 0.0),
                current_amps=float(r["current_amps"] or 0.0),
                voltage_volts=float(r["voltage_volts"] or 0.0),
            ),
        )
    return datamesh_pb2.TelemetryPacket(
        device_id=dev_id,
        device_type=dev_type,
        timestamp_ms=ts_ms,
        is_alert=alert,
    )


class SQLiteTelemetryStorage:
    """Manages raw SQLite storage operations for telemetry readings."""

    def __init__(self, db_path: str = "datamesh.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def __enter__(self) -> "SQLiteTelemetryStorage":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def close(self) -> None:
        """Closes the underlying database connection."""
        with self._lock:
            self._conn.close()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA_DDL)
            self._conn.commit()

    def record_telemetry(self, packet: datamesh_pb2.TelemetryPacket) -> None:
        """Persists a single telemetry or alert packet into SQLite.

        Example:
            storage.record_telemetry(packet)
        """
        which = packet.WhichOneof("payload")
        temp = (
            packet.temperature.temperature_c
            if which == "temperature"
            else (packet.ac.temperature_c if which == "ac" else 0.0)
        )
        target = packet.ac.target_temp_c if which == "ac" else 0.0
        fan = packet.ac.fan_speed_pct if which == "ac" else 0
        power = (
            packet.ac.power_watts
            if which == "ac"
            else (packet.pdu.power_watts if which == "pdu" else 0.0)
        )
        current = (
            packet.ac.current_amps
            if which == "ac"
            else (packet.pdu.current_amps if which == "pdu" else 0.0)
        )
        voltage = (
            packet.ac.voltage_volts
            if which == "ac"
            else (packet.pdu.voltage_volts if which == "pdu" else 0.0)
        )
        ac_on = packet.ac.ac_power_on if which == "ac" else False

        values = (
            packet.device_id,
            packet.device_type,
            packet.timestamp_ms,
            int(packet.is_alert),
            temp,
            target,
            fan,
            power,
            current,
            voltage,
            int(ac_on),
        )
        with self._lock:
            self._conn.execute(INSERT_TELEMETRY_SQL, values)
            self._conn.commit()

    def get_recent_history(self, limit: int = 50) -> list[datamesh_pb2.TelemetryPacket]:
        """Returns the most recent readings in chronological order.

        Example:
            history = storage.get_recent_history(limit=10)
        """
        with self._lock:
            rows = self._conn.execute(SELECT_RECENT_HISTORY_SQL, (limit,)).fetchall()

        packets = [_row_to_telemetry_packet(r) for r in rows]
        return packets[::-1]

    def fetch_hottest_rack_raw(self, cutoff_ms: int) -> tuple[str | None, float | None, int]:
        """Executes query to find peak temperature in time window.

        Example:
            device, peak, count = storage.fetch_hottest_rack_raw(cutoff_ms)
        """
        with self._lock:
            row = self._conn.execute(SELECT_HOTTEST_RACK_SQL, (cutoff_ms, cutoff_ms)).fetchone()
        if not row or row["sample_count"] == 0 or row["max_temp"] is None:
            return (None, None, 0)
        return (row["hottest_device"], row["max_temp"], row["sample_count"])

    def fetch_avg_pdu_power_raw(self, cutoff_ms: int) -> tuple[float | None, int]:
        """Executes query for average PDU power in time window.

        Example:
            avg_pwr, count = storage.fetch_avg_pdu_power_raw(cutoff_ms)
        """
        with self._lock:
            row = self._conn.execute(
                SELECT_AVG_PDU_POWER_SQL, (datamesh_pb2.RACK_PDU, cutoff_ms)
            ).fetchone()
        if not row or row["sample_count"] == 0 or row["avg_power"] is None:
            return (None, 0)
        return (row["avg_power"], row["sample_count"])

    def fetch_temperatures_raw(self, cutoff_ms: int) -> list[float]:
        """Fetches all valid positive temperatures in time window.

        Example:
            temps = storage.fetch_temperatures_raw(cutoff_ms)
        """
        with self._lock:
            rows = self._conn.execute(SELECT_THERMAL_STABILITY_SQL, (cutoff_ms,)).fetchall()
        return [r["temperature_c"] for r in rows if r["temperature_c"] is not None]
