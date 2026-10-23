"""TCP Client adapter communicating with Gateway using length-prefixed Protobuf framing."""

import logging
import socket
from typing import Protocol

import datamesh_pb2

from common.framing import recv_proto, send_proto

logger = logging.getLogger(__name__)

DEFAULT_GATEWAY_HOST = "127.0.0.1"
DEFAULT_GATEWAY_PORT = 9997
DEFAULT_TIMEOUT_SEC = 3.0
DEFAULT_HISTORY_LIMIT = 100
DEFAULT_WINDOW_SECONDS = 300


class GatewayClientProtocol(Protocol):
    """Protocol defining the operations available to query and control the DCIM Gateway."""

    def list_devices(self) -> list[datamesh_pb2.DeviceInfo]:
        """Lists active and registered devices from the Gateway."""
        ...

    def control_ac(
        self,
        device_id: str,
        power_on: bool,
        target_temp_c: float,
        fan_speed_pct: int,
    ) -> tuple[bool, str]:
        """Sends an actuation control command to a precision air conditioner."""
        ...

    def get_history(self, limit: int = DEFAULT_HISTORY_LIMIT) -> list[datamesh_pb2.TelemetryPacket]:
        """Retrieves recent time-series telemetry records from the Gateway."""
        ...

    def query_analytics(
        self,
        query_type: datamesh_pb2.AnalyticsQueryType,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> datamesh_pb2.AnalyticsResult:
        """Executes an analytical aggregation query over a rolling time window."""
        ...


class TCPGatewayClient:
    """Client implementing communication with the DataMesh Gateway over TCP sockets."""

    def __init__(
        self,
        host: str = DEFAULT_GATEWAY_HOST,
        port: int = DEFAULT_GATEWAY_PORT,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec

    def _execute_request(self, request: datamesh_pb2.ClientRequest) -> datamesh_pb2.ClientResponse:
        """Opens a short-lived TCP connection, dispatches framed request, and returns response."""
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout_sec) as sock:
                send_proto(sock, request)
                return recv_proto(sock, datamesh_pb2.ClientResponse)
        except (TimeoutError, ConnectionError, OSError) as err:
            logger.warning(
                "TCP communication error with Gateway (%s:%d): %s",
                self.host,
                self.port,
                err,
            )
            return datamesh_pb2.ClientResponse(
                success=False,
                message=f"Gateway connection error: {err}",
            )

    def list_devices(self) -> list[datamesh_pb2.DeviceInfo]:
        """Retrieves the list of discovered data sources and their status from the Gateway.

        Example:
            devices = client.list_devices()
        """
        req = datamesh_pb2.ClientRequest(action=datamesh_pb2.LIST_DEVICES)
        resp = self._execute_request(req)
        return list(resp.devices) if resp.success else []

    def control_ac(
        self,
        device_id: str,
        power_on: bool,
        target_temp_c: float,
        fan_speed_pct: int,
    ) -> tuple[bool, str]:
        """Dispatches an actuation command to adjust temperature, fan, or power of an AC unit.

        Example:
            ok, msg = client.control_ac("ac-1", True, 20.0, 75)
        """
        req = datamesh_pb2.ClientRequest(
            action=datamesh_pb2.CONTROL_AC,
            ac_control=datamesh_pb2.ACControlRequest(
                device_id=device_id,
                power_on=power_on,
                target_temp_c=target_temp_c,
                fan_speed_pct=fan_speed_pct,
            ),
        )
        resp = self._execute_request(req)
        return resp.success, resp.message

    def get_history(self, limit: int = DEFAULT_HISTORY_LIMIT) -> list[datamesh_pb2.TelemetryPacket]:
        """Fetches the most recent time-series telemetry packets for dashboard charts.

        Example:
            records = client.get_history(limit=50)
        """
        req = datamesh_pb2.ClientRequest(
            action=datamesh_pb2.GET_HISTORY,
            history_limit=limit,
        )
        resp = self._execute_request(req)
        return list(resp.history) if resp.success else []

    def query_analytics(
        self,
        query_type: datamesh_pb2.AnalyticsQueryType,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> datamesh_pb2.AnalyticsResult:
        """Executes an aggregated metric query over a rolling window.

        Example:
            res = client.query_analytics(datamesh_pb2.HOTTEST_RACK, 300)
        """
        req = datamesh_pb2.ClientRequest(
            action=datamesh_pb2.QUERY_ANALYTICS,
            query_type=query_type,
            window_seconds=window_seconds,
        )
        resp = self._execute_request(req)
        if resp.success and resp.HasField("analytics"):
            return resp.analytics
        return datamesh_pb2.AnalyticsResult(
            query_type=query_type,
            summary=resp.message or "Erro ao consultar analytics no Gateway.",
        )
