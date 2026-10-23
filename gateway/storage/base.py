"""Protocols and interfaces for telemetry persistence and analytical queries."""

from typing import Protocol

import datamesh_pb2


class TelemetryStorageProtocol(Protocol):
    """Interface defining storage operations for telemetry time-series."""

    def record_telemetry(self, packet: datamesh_pb2.TelemetryPacket) -> None: ...

    def get_recent_history(self, limit: int = 50) -> list[datamesh_pb2.TelemetryPacket]: ...

    def close(self) -> None: ...


class AnalyticsProtocol(Protocol):
    """Interface defining analytical queries for DataMesh DCIM."""

    def query_hottest_rack(
        self, window_seconds: int, reference_time_ms: int | None = None
    ) -> datamesh_pb2.AnalyticsResult: ...

    def query_average_pdu_power(
        self, window_seconds: int, reference_time_ms: int | None = None
    ) -> datamesh_pb2.AnalyticsResult: ...

    def query_thermal_stability(
        self, window_seconds: int, reference_time_ms: int | None = None
    ) -> datamesh_pb2.AnalyticsResult: ...
