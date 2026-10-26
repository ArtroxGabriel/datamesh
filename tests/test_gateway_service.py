import socket
from collections.abc import Generator

import datamesh_pb2
import pytest

from common.framing import recv_proto, send_proto
from gateway.registry import DeviceRegistry
from gateway.service import ACControlProxy, GatewayCoordinator
from gateway.storage import TelemetryStorage


class FakeACControlProxy(ACControlProxy):
    """Fake AC proxy for fast, deterministic unit testing of gRPC dispatch."""

    def __init__(self, should_succeed: bool = True) -> None:
        self.should_succeed = should_succeed
        self.last_command: datamesh_pb2.ACControlRequest | None = None

    def send_ac_control(
        self, device: datamesh_pb2.DeviceInfo, command: datamesh_pb2.ACControlRequest
    ) -> datamesh_pb2.ACControlResponse:
        self.last_command = command
        if not self.should_succeed:
            return datamesh_pb2.ACControlResponse(success=False, message="AC unit unreachable")
        updated_dev = datamesh_pb2.DeviceInfo()
        updated_dev.CopyFrom(device)
        updated_dev.state_summary = f"AC ON | Setpoint: {command.target_temp_c:.1f}C"
        return datamesh_pb2.ACControlResponse(
            success=True,
            message=f"Setpoint adjusted to {command.target_temp_c:.1f}C",
            updated_device=updated_dev,
        )


@pytest.fixture
def coordinator() -> Generator[GatewayCoordinator]:
    storage = TelemetryStorage(":memory:")
    registry = DeviceRegistry()
    proxy = FakeACControlProxy(should_succeed=True)
    coord = GatewayCoordinator(storage=storage, registry=registry, ac_proxy=proxy)
    try:
        yield coord
    finally:
        coord.close()


def test_handles_list_devices_request(coordinator: GatewayCoordinator) -> None:
    # Arrange
    device = datamesh_pb2.DeviceInfo(
        device_id="ac-01",
        device_type=datamesh_pb2.AIR_CONDITIONER,
        is_online=True,
        last_seen_ms=1000,
    )
    coordinator.registry.register_device(device)

    req = datamesh_pb2.ClientRequest(action=datamesh_pb2.LIST_DEVICES)

    # Act
    resp = coordinator.handle_client_request(req, current_time_ms=1000)

    # Assert
    assert resp.success is True
    assert len(resp.devices) == 1
    assert resp.devices[0].device_id == "ac-01"


def test_handles_get_history_request(coordinator: GatewayCoordinator) -> None:
    # Arrange
    coordinator.storage.record_telemetry(
        datamesh_pb2.TelemetryPacket(
            device_id="temp-01",
            device_type=datamesh_pb2.TEMPERATURE_SENSOR,
            timestamp_ms=1000,
            temperature=datamesh_pb2.TemperatureTelemetry(temperature_c=25.0),
        )
    )
    req = datamesh_pb2.ClientRequest(
        action=datamesh_pb2.GET_HISTORY,
        history_limit=10,
    )

    # Act
    resp = coordinator.handle_client_request(req)

    # Assert
    assert resp.success is True
    assert len(resp.history) == 1
    assert resp.history[0].device_id == "temp-01"


def test_handles_query_analytics_requests(coordinator: GatewayCoordinator) -> None:
    # Arrange
    import time

    now_ms = int(time.time() * 1000)
    coordinator.storage.record_telemetry(
        datamesh_pb2.TelemetryPacket(
            device_id="temp-01",
            device_type=datamesh_pb2.TEMPERATURE_SENSOR,
            timestamp_ms=now_ms,
            temperature=datamesh_pb2.TemperatureTelemetry(temperature_c=32.0),
        )
    )
    coordinator.storage.record_telemetry(
        datamesh_pb2.TelemetryPacket(
            device_id="pdu-01",
            device_type=datamesh_pb2.RACK_PDU,
            timestamp_ms=now_ms,
            pdu=datamesh_pb2.PDUTelemetry(power_watts=1500.0),
        )
    )

    hottest_req = datamesh_pb2.ClientRequest(
        action=datamesh_pb2.QUERY_ANALYTICS,
        query_type=datamesh_pb2.HOTTEST_RACK,
        window_seconds=10,
    )
    pdu_req = datamesh_pb2.ClientRequest(
        action=datamesh_pb2.QUERY_ANALYTICS,
        query_type=datamesh_pb2.AVG_PDU_POWER,
        window_seconds=10,
    )
    stability_req = datamesh_pb2.ClientRequest(
        action=datamesh_pb2.QUERY_ANALYTICS,
        query_type=datamesh_pb2.THERMAL_STABILITY,
        window_seconds=10,
    )

    # Act
    hottest_resp = coordinator.handle_client_request(hottest_req)
    pdu_resp = coordinator.handle_client_request(pdu_req)
    stability_resp = coordinator.handle_client_request(stability_req)

    # Assert
    assert hottest_resp.success is True
    assert hottest_resp.analytics.target_device_id == "temp-01"
    assert pdu_resp.success is True
    assert abs(pdu_resp.analytics.primary_value - 1500.0) < 1e-4
    assert stability_resp.success is True
    assert abs(stability_resp.analytics.primary_value - 32.0) < 1e-4


def test_handles_ac_control_success(coordinator: GatewayCoordinator) -> None:
    # Arrange
    device = datamesh_pb2.DeviceInfo(
        device_id="ac-rack-01",
        device_type=datamesh_pb2.AIR_CONDITIONER,
        ip="127.0.0.1",
        grpc_port=50051,
        last_seen_ms=1000,
    )
    coordinator.registry.register_device(device)

    req = datamesh_pb2.ClientRequest(
        action=datamesh_pb2.CONTROL_AC,
        ac_control=datamesh_pb2.ACControlRequest(
            device_id="ac-rack-01",
            power_on=True,
            target_temp_c=19.5,
            fan_speed_pct=85,
        ),
    )

    # Act
    resp = coordinator.handle_client_request(req, current_time_ms=1000)

    # Assert
    assert resp.success is True
    assert "19.5C" in resp.message
    updated = coordinator.registry.get_device("ac-rack-01", current_time_ms=1000)
    assert updated is not None and "19.5C" in updated.state_summary


def test_handles_ac_control_target_not_found(coordinator: GatewayCoordinator) -> None:
    # Arrange
    req = datamesh_pb2.ClientRequest(
        action=datamesh_pb2.CONTROL_AC,
        ac_control=datamesh_pb2.ACControlRequest(
            device_id="non-existent-ac",
            power_on=True,
            target_temp_c=20.0,
        ),
    )

    # Act
    resp = coordinator.handle_client_request(req)

    # Assert
    assert resp.success is False
    assert "not found" in resp.message.lower()


def test_handles_udp_datagram_for_discovery_and_telemetry(
    coordinator: GatewayCoordinator,
) -> None:
    # Arrange: discovery announcement datagram
    discovery_msg = datamesh_pb2.DeviceInfo(
        device_id="temp-sensor-01",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        ip="192.168.1.50",
        last_seen_ms=5000,
    )
    # Arrange: telemetry datagram
    telemetry_msg = datamesh_pb2.TelemetryPacket(
        device_id="temp-sensor-01",
        device_type=datamesh_pb2.TEMPERATURE_SENSOR,
        timestamp_ms=5500,
        temperature=datamesh_pb2.TemperatureTelemetry(temperature_c=26.3),
    )

    # Act
    coordinator.handle_udp_datagram(discovery_msg.SerializeToString(), ("192.168.1.50", 9998))
    coordinator.handle_udp_datagram(telemetry_msg.SerializeToString(), ("192.168.1.50", 9998))

    # Assert
    device = coordinator.registry.get_device("temp-sensor-01", current_time_ms=5500)
    history = coordinator.storage.get_recent_history(limit=5)
    assert device is not None
    assert device.device_id == "temp-sensor-01"
    assert len(history) == 1
    assert abs(history[0].temperature.temperature_c - 26.3) < 1e-4


def test_tcp_server_accepts_and_responds_over_real_socket(
    coordinator: GatewayCoordinator,
) -> None:
    # Arrange: start TCP server on ephemeral port (port 0)
    server_port = coordinator.start_tcp_server(host="127.0.0.1", port=0)

    try:
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(("127.0.0.1", server_port))

        req = datamesh_pb2.ClientRequest(action=datamesh_pb2.LIST_DEVICES)
        send_proto(client_sock, req)
        resp = recv_proto(client_sock, datamesh_pb2.ClientResponse)

        assert resp.success is True
        assert resp.devices == []
    finally:
        client_sock.close()
        coordinator.stop_tcp_server()


def test_grpc_proxy_error_handling() -> None:
    # Arrange: proxy target that cannot be connected
    from gateway.proxy import GrpcACControlProxy

    proxy = GrpcACControlProxy(timeout_seconds=0.1)
    device = datamesh_pb2.DeviceInfo(
        device_id="ac-dead",
        device_type=datamesh_pb2.AIR_CONDITIONER,
        ip="127.0.0.1",
        grpc_port=59999,
    )
    cmd = datamesh_pb2.ACControlRequest(
        device_id="ac-dead",
        power_on=True,
        target_temp_c=20.0,
    )

    # Act
    resp = proxy.send_ac_control(device, cmd)

    # Assert
    assert resp.success is False
    assert "error" in resp.message.lower() or "failed" in resp.message.lower()


def test_handles_unknown_action_and_query_type(coordinator: GatewayCoordinator) -> None:
    # Arrange
    unknown_action = datamesh_pb2.ClientRequest(action=datamesh_pb2.CLIENT_ACTION_UNKNOWN)
    unknown_query = datamesh_pb2.ClientRequest(
        action=datamesh_pb2.QUERY_ANALYTICS,
        query_type=datamesh_pb2.ANALYTICS_QUERY_UNKNOWN,
    )

    # Act
    resp_action = coordinator.handle_client_request(unknown_action)
    resp_query = coordinator.handle_client_request(unknown_query)

    # Assert
    assert resp_action.success is False
    assert "unknown client action" in resp_action.message.lower()
    assert resp_query.success is False
    assert "unsupported query type" in resp_query.message.lower()


def test_ac_control_empty_response_message_fallback(
    coordinator: GatewayCoordinator,
) -> None:
    # Arrange: proxy returns success=False with empty message ""
    coordinator.registry.register_device(
        datamesh_pb2.DeviceInfo(
            device_id="ac-empty",
            device_type=datamesh_pb2.AIR_CONDITIONER,
            ip="127.0.0.1",
            grpc_port=50051,
        )
    )

    class EmptyMessageProxy(ACControlProxy):
        def send_ac_control(
            self, device: datamesh_pb2.DeviceInfo, command: datamesh_pb2.ACControlRequest
        ) -> datamesh_pb2.ACControlResponse:
            return datamesh_pb2.ACControlResponse(success=False, message="")

    coordinator.ac_proxy = EmptyMessageProxy()
    req = datamesh_pb2.ClientRequest(
        action=datamesh_pb2.CONTROL_AC,
        ac_control=datamesh_pb2.ACControlRequest(
            device_id="ac-empty",
            power_on=False,
        ),
    )

    # Act
    resp = coordinator.handle_client_request(req)

    # Assert
    assert resp.success is False
    assert resp.message == "AC command failed"
    # Ensure framing can serialize it without raising ValueError
    from common.framing import send_proto

    left, right = socket.socketpair()
    try:
        send_proto(left, resp)
    finally:
        left.close()
        right.close()


def test_gateway_app_lifecycle() -> None:
    # Arrange
    from gateway.main import GatewayApp

    app = GatewayApp(
        host="127.0.0.1",
        tcp_port=0,
        udp_port=0,
        advertised_ip="192.168.1.100",
        db_path=":memory:",
    )

    # Act & Assert
    assert app.advertised_ip == "192.168.1.100"
    app.start()
    assert app._running is True
    app.stop()
    assert app._running is False


def test_gateway_and_client_share_default_tcp_port() -> None:
    from client.gateway_client import DEFAULT_GATEWAY_PORT
    from client.main import _load_config
    from gateway.main import DEFAULT_TCP_PORT, GatewayApp

    app = GatewayApp(db_path=":memory:")
    _, _, _, client_gw_port = _load_config()

    assert DEFAULT_TCP_PORT == DEFAULT_GATEWAY_PORT == 9997
    assert app.tcp_port == client_gw_port == 9997
    app.stop()
