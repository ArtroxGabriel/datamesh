"""Analytical queries and mathematical aggregations for DataMesh DCIM."""

import statistics
import time

import datamesh_pb2

from gateway.storage.sqlite import SQLiteTelemetryStorage

MILLIS_PER_SECOND = 1000


class AnalyticsEngine:
    """Calculates DCIM aggregated metrics over telemetry time windows."""

    def __init__(self, storage: SQLiteTelemetryStorage) -> None:
        self._storage = storage

    def _compute_cutoff_ms(self, window_seconds: int, reference_time_ms: int | None) -> int:
        now_ms = reference_time_ms if reference_time_ms is not None else int(time.time() * 1000)
        return now_ms - (window_seconds * MILLIS_PER_SECOND)

    def query_hottest_rack(
        self, window_seconds: int, reference_time_ms: int | None = None
    ) -> datamesh_pb2.AnalyticsResult:
        """Finds the device with peak temperature in the specified time window.

        Example:
            result = analytics.query_hottest_rack(window_seconds=300)
        """
        cutoff_ms = self._compute_cutoff_ms(window_seconds, reference_time_ms)
        device_id, max_temp, count = self._storage.fetch_hottest_rack_raw(cutoff_ms)

        if count == 0 or max_temp is None or device_id is None:
            return datamesh_pb2.AnalyticsResult(
                query_type=datamesh_pb2.HOTTEST_RACK,
                unit="°C",
                summary="Nenhuma leitura térmica encontrada na janela selecionada.",
            )

        return datamesh_pb2.AnalyticsResult(
            query_type=datamesh_pb2.HOTTEST_RACK,
            target_device_id=device_id,
            primary_value=max_temp,
            unit="°C",
            summary=f"Rack {device_id} registrou pico de {max_temp:.1f} °C",
            sample_count=count,
        )

    def query_average_pdu_power(
        self, window_seconds: int, reference_time_ms: int | None = None
    ) -> datamesh_pb2.AnalyticsResult:
        """Calculates average power consumption of all PDUs in the specified time window.

        Example:
            result = analytics.query_average_pdu_power(window_seconds=600)
        """
        cutoff_ms = self._compute_cutoff_ms(window_seconds, reference_time_ms)
        avg_power, count = self._storage.fetch_avg_pdu_power_raw(cutoff_ms)

        if count == 0 or avg_power is None:
            return datamesh_pb2.AnalyticsResult(
                query_type=datamesh_pb2.AVG_PDU_POWER,
                unit="W",
                summary="Nenhuma leitura de PDU encontrada na janela selecionada.",
            )

        return datamesh_pb2.AnalyticsResult(
            query_type=datamesh_pb2.AVG_PDU_POWER,
            primary_value=avg_power,
            unit="W",
            summary=f"Consumo médio de potência das PDUs: {avg_power:.1f} W",
            sample_count=count,
        )

    def query_thermal_stability(
        self, window_seconds: int, reference_time_ms: int | None = None
    ) -> datamesh_pb2.AnalyticsResult:
        """Calculates thermal mean and standard deviation across racks in the time window.

        Example:
            result = analytics.query_thermal_stability(window_seconds=300)
        """
        cutoff_ms = self._compute_cutoff_ms(window_seconds, reference_time_ms)
        temps = self._storage.fetch_temperatures_raw(cutoff_ms)

        if not temps:
            return datamesh_pb2.AnalyticsResult(
                query_type=datamesh_pb2.THERMAL_STABILITY,
                unit="°C",
                summary="Nenhuma leitura de temperatura encontrada na janela selecionada.",
            )

        mean_val = statistics.mean(temps)
        std_val = statistics.pstdev(temps) if len(temps) > 1 else 0.0
        summary_text = (
            f"Estabilidade térmica: média {mean_val:.1f} °C, desvio padrão {std_val:.2f} °C"
        )
        return datamesh_pb2.AnalyticsResult(
            query_type=datamesh_pb2.THERMAL_STABILITY,
            primary_value=mean_val,
            secondary_value=std_val,
            unit="°C",
            summary=summary_text,
            sample_count=len(temps),
        )
