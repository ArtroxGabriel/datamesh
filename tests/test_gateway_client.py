"""Unit tests for TCP Gateway Client adapter."""

import socket
import threading
from collections.abc import Generator

import datamesh_pb2
import pytest

from client.gateway_client import TCPGatewayClient
from common.framing import recv_proto, send_proto


class MockGatewayServer:
    """Mock TCP server speaking length-prefixed Protobuf for testing TCPGatewayClient."""

    def __init__(self) -> None:
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", 0))
        self.server_sock.listen(5)
        self.port: int = self.server_sock.getsockname()[1]
        self.running = True
        self.received_requests: list[datamesh_pb2.ClientRequest] = []
        self.response_to_send: datamesh_pb2.ClientResponse = datamesh_pb2.ClientResponse(
            success=True, message="OK"
        )
        self.thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.thread.start()

    def _listen_loop(self) -> None:
        self.server_sock.settimeout(0.2)
        while self.running:
            try:
                conn, _ = self.server_sock.accept()
            except TimeoutError:
                continue
            except Exception:
                break
            try:
                req = recv_proto(conn, datamesh_pb2.ClientRequest)
                if req:
                    self.received_requests.append(req)
                    send_proto(conn, self.response_to_send)
            finally:
                conn.close()

    def stop(self) -> None:
        self.running = False
        try:
            self.server_sock.close()
        except Exception:
            pass


@pytest.fixture
def mock_gateway() -> Generator[MockGatewayServer]:
    server = MockGatewayServer()
    try:
        yield server
    finally:
        server.stop()


def test_list_devices_dispatches_tcp_request(mock_gateway: MockGatewayServer) -> None:
    # Arrange
    mock_gateway.response_to_send = datamesh_pb2.ClientResponse(
        success=True,
        message="Devices retrieved",
        devices=[
            datamesh_pb2.DeviceInfo(
                device_id="temp-rack-01",
                device_type=datamesh_pb2.TEMPERATURE_SENSOR,
                is_online=True,
                state_summary="24.2 °C",
            ),
            datamesh_pb2.DeviceInfo(
                device_id="ac-rack-01",
                device_type=datamesh_pb2.AIR_CONDITIONER,
                is_online=True,
                state_summary="AC ON | 21.0 °C",
            ),
        ],
    )
    client = TCPGatewayClient(host="127.0.0.1", port=mock_gateway.port)

    # Act
    devices = client.list_devices()

    # Assert
    assert len(devices) == 2
    assert devices[0].device_id == "temp-rack-01"
    assert devices[1].device_id == "ac-rack-01"
    assert len(mock_gateway.received_requests) == 1
    assert mock_gateway.received_requests[0].action == datamesh_pb2.LIST_DEVICES


def test_control_ac_sends_command_payload(mock_gateway: MockGatewayServer) -> None:
    # Arrange
    mock_gateway.response_to_send = datamesh_pb2.ClientResponse(
        success=True,
        message="AC setpoint adjusted to 19.5 C",
    )
    client = TCPGatewayClient(host="127.0.0.1", port=mock_gateway.port)

    # Act
    success, msg = client.control_ac(
        device_id="ac-rack-01",
        power_on=True,
        target_temp_c=19.5,
        fan_speed_pct=80,
    )

    # Assert
    assert success is True
    assert "19.5 C" in msg
    assert len(mock_gateway.received_requests) == 1
    req = mock_gateway.received_requests[0]
    assert req.action == datamesh_pb2.CONTROL_AC
    assert req.ac_control.device_id == "ac-rack-01"
    assert req.ac_control.power_on is True
    assert req.ac_control.target_temp_c == 19.5
    assert req.ac_control.fan_speed_pct == 80


def test_get_history_sends_limit_and_unpacks_packets(
    mock_gateway: MockGatewayServer,
) -> None:
    # Arrange
    mock_gateway.response_to_send = datamesh_pb2.ClientResponse(
        success=True,
        message="History OK",
        history=[
            datamesh_pb2.TelemetryPacket(
                device_id="temp-rack-01",
                temperature_c=25.0,
                timestamp_ms=1000,
            ),
            datamesh_pb2.TelemetryPacket(
                device_id="pdu-rack-01",
                power_watts=1400.0,
                timestamp_ms=1001,
            ),
        ],
    )
    client = TCPGatewayClient(host="127.0.0.1", port=mock_gateway.port)

    # Act
    history = client.get_history(limit=50)

    # Assert
    assert len(history) == 2
    assert history[0].device_id == "temp-rack-01"
    assert history[1].device_id == "pdu-rack-01"
    assert len(mock_gateway.received_requests) == 1
    assert mock_gateway.received_requests[0].action == datamesh_pb2.GET_HISTORY
    assert mock_gateway.received_requests[0].history_limit == 50


def test_query_analytics_sends_query_type_and_window(
    mock_gateway: MockGatewayServer,
) -> None:
    # Arrange
    mock_gateway.response_to_send = datamesh_pb2.ClientResponse(
        success=True,
        analytics=datamesh_pb2.AnalyticsResult(
            query_type=datamesh_pb2.HOTTEST_RACK,
            target_device_id="temp-rack-01",
            primary_value=32.5,
            unit="°C",
            summary="Rack temp-rack-01 registrou pico de 32.5 °C",
            sample_count=42,
        ),
    )
    client = TCPGatewayClient(host="127.0.0.1", port=mock_gateway.port)

    # Act
    res = client.query_analytics(
        query_type=datamesh_pb2.HOTTEST_RACK,
        window_seconds=600,
    )

    # Assert
    assert res.query_type == datamesh_pb2.HOTTEST_RACK
    assert res.target_device_id == "temp-rack-01"
    assert res.primary_value == 32.5
    assert res.sample_count == 42
    assert len(mock_gateway.received_requests) == 1
    req = mock_gateway.received_requests[0]
    assert req.action == datamesh_pb2.QUERY_ANALYTICS
    assert req.query_type == datamesh_pb2.HOTTEST_RACK
    assert req.window_seconds == 600


def test_gateway_connection_refused_returns_error() -> None:
    # Arrange: use an unallocated port where no gateway is listening
    client = TCPGatewayClient(host="127.0.0.1", port=59999, timeout_sec=0.2)

    # Act
    devices = client.list_devices()
    success, msg = client.control_ac("ac-1", True, 20.0, 50)
    history = client.get_history(10)
    analytics = client.query_analytics(datamesh_pb2.AVG_PDU_POWER, 300)

    # Assert: All graceful fallbacks without unhandled exceptions
    assert devices == []
    assert success is False
    assert "error" in msg.lower() or "connection" in msg.lower()
    assert history == []
    assert analytics.summary != ""


def test_gateway_closes_connection_without_response() -> None:
    # Arrange: mock server that accepts, receives request, and closes without responding
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    def _accept_recv_and_close() -> None:
        conn, _ = server_sock.accept()
        # Read the framed request from client before closing
        recv_proto(conn, datamesh_pb2.ClientRequest)
        conn.close()
        server_sock.close()

    t = threading.Thread(target=_accept_recv_and_close, daemon=True)
    t.start()

    client = TCPGatewayClient(host="127.0.0.1", port=port, timeout_sec=1.0)

    # Act
    devices = client.list_devices()

    # Assert
    assert devices == []
