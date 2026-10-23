"""Storage module for DataMesh DCIM Gateway."""

import datamesh_pb2

from gateway.storage.analytics import AnalyticsEngine
from gateway.storage.base import (
    AnalyticsProtocol,
    GatewayStorageProtocol,
    TelemetryStorageProtocol,
)
from gateway.storage.sqlite import SQLiteTelemetryStorage


class TelemetryStorage:
    """Unified storage and analytics facade for DataMesh DCIM Gateway."""

    def __init__(self, db_path: str = "datamesh.db") -> None:
        self._sqlite = SQLiteTelemetryStorage(db_path)
        self._analytics = AnalyticsEngine(self._sqlite)

    def __enter__(self) -> "TelemetryStorage":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def close(self) -> None:
        """Closes the underlying database connection."""
        self._sqlite.close()

    def record_telemetry(self, packet: datamesh_pb2.TelemetryPacket) -> None:
        """Persists a single telemetry or alert packet.

        Example:
            storage.record_telemetry(packet)
        """
        self._sqlite.record_telemetry(packet)

    def get_recent_history(self, limit: int = 50) -> list[datamesh_pb2.TelemetryPacket]:
        """Returns the most recent readings in chronological order.

        Example:
            history = storage.get_recent_history(limit=20)
        """
        return self._sqlite.get_recent_history(limit)

    def query_hottest_rack(
        self, window_seconds: int, reference_time_ms: int | None = None
    ) -> datamesh_pb2.AnalyticsResult:
        """Queries peak temperature in time window.

        Example:
            result = storage.query_hottest_rack(window_seconds=300)
        """
        return self._analytics.query_hottest_rack(window_seconds, reference_time_ms)

    def query_average_pdu_power(
        self, window_seconds: int, reference_time_ms: int | None = None
    ) -> datamesh_pb2.AnalyticsResult:
        """Queries average PDU power in time window.

        Example:
            result = storage.query_average_pdu_power(window_seconds=600)
        """
        return self._analytics.query_average_pdu_power(window_seconds, reference_time_ms)

    def query_thermal_stability(
        self, window_seconds: int, reference_time_ms: int | None = None
    ) -> datamesh_pb2.AnalyticsResult:
        """Queries thermal mean and stddev in time window.

        Example:
            result = storage.query_thermal_stability(window_seconds=300)
        """
        return self._analytics.query_thermal_stability(window_seconds, reference_time_ms)


__all__ = [
    "AnalyticsEngine",
    "AnalyticsProtocol",
    "GatewayStorageProtocol",
    "SQLiteTelemetryStorage",
    "TelemetryStorage",
    "TelemetryStorageProtocol",
]
