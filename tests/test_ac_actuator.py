"""Unit tests for Precision Air Conditioner actuator source."""

import socket
import time

import datamesh_pb2
import pytest

from gateway.proxy import GrpcACControlProxy
from sources.ac.actuator import (
    DEFAULT_FAN_SPEED_PCT,
    DEFAULT_TARGET_TEMP_C,
    AirConditionerDevice,
    AirConditionerServicer,
)


class FakeUDPSocket:
    """In-memory UDP socket fake to capture transmitted datagrams."""

    def __init__(self) -> None:
        self.sent_packets: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, data: bytes, target: tuple[str, int], /) -> int:
        self.sent_packets.append((data, target))
        return len(data)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_socket() -> FakeUDPSocket:
    return FakeUDPSocket()


def test_initial_state_and_device_info(fake_socket: FakeUDPSocket) -> None:
    # Arrange & Act
    device = AirConditionerDevice(
        device_id="ac-rack-01",
        grpc_port=50051,
        gateway_host="127.0.0.1",
        gateway_port=9998,
        socket_factory=lambda: fake_socket,
    )
    info = device.to_device_info()

    # Assert
    assert info.device_id == "ac-rack-01"
    assert info.device_type == datamesh_pb2.AIR_CONDITIONER
    assert info.grpc_port == 50051
    assert info.is_online is True
    assert "AC ON" in info.state_summary
    assert f"{DEFAULT_TARGET_TEMP_C:.1f}°C" in info.state_summary


def test_grpc_servicer_set_control_updates_device_state(
    fake_socket: FakeUDPSocket,
) -> None:
    # Arrange
    device = AirConditionerDevice(
        device_id="ac-rack-01",
        grpc_port=50051,
        socket_factory=lambda: fake_socket,
    )
    servicer = AirConditionerServicer(device)
    cmd = datamesh_pb2.ACControlRequest(
        device_id="ac-rack-01",
        power_on=True,
        target_temp_c=19.5,
        fan_speed_pct=85,
    )

    # Act
    resp = servicer.SetControl(cmd, None)

    # Assert
    assert resp.success is True
    assert "updated" in resp.message.lower()
    assert resp.updated_device.device_id == "ac-rack-01"
    assert device.target_temp_c == 19.5
    assert device.fan_speed_pct == 85
    assert device.power_on is True


def test_grpc_servicer_turns_power_off(fake_socket: FakeUDPSocket) -> None:
    # Arrange
    device = AirConditionerDevice(
        device_id="ac-rack-01",
        grpc_port=50051,
        socket_factory=lambda: fake_socket,
    )
    servicer = AirConditionerServicer(device)
    cmd = datamesh_pb2.ACControlRequest(
        device_id="ac-rack-01",
        power_on=False,
        target_temp_c=22.0,
        fan_speed_pct=0,
    )

    # Act
    resp = servicer.SetControl(cmd, None)

    # Assert
    assert resp.success is True
    assert device.power_on is False
    assert device.fan_speed_pct == 0
    assert "OFF" in resp.updated_device.state_summary


def test_creates_periodic_telemetry_packet(fake_socket: FakeUDPSocket) -> None:
    # Arrange
    device = AirConditionerDevice(
        device_id="ac-rack-01",
        grpc_port=50051,
        gateway_host="127.0.0.1",
        gateway_port=9998,
        socket_factory=lambda: fake_socket,
    )

    # Act
    packet = device.create_telemetry()

    # Assert
    assert packet.device_id == "ac-rack-01"
    assert packet.device_type == datamesh_pb2.AIR_CONDITIONER
    assert packet.is_alert is False
    assert packet.WhichOneof("payload") == "ac"
    assert packet.ac.ac_power_on is True
    assert packet.ac.target_temp_c == DEFAULT_TARGET_TEMP_C
    assert packet.ac.fan_speed_pct == DEFAULT_FAN_SPEED_PCT
    assert packet.ac.power_watts > 0
    assert packet.ac.voltage_volts > 0
    assert packet.timestamp_ms > 0


def test_send_telemetry_transmits_over_udp(fake_socket: FakeUDPSocket) -> None:
    # Arrange
    device = AirConditionerDevice(
        device_id="ac-rack-01",
        gateway_host="127.0.0.1",
        gateway_port=9998,
        socket_factory=lambda: fake_socket,
    )

    # Act
    packet = device.send_telemetry()

    # Assert
    assert packet is not None
    assert len(fake_socket.sent_packets) == 1
    raw_bytes, target = fake_socket.sent_packets[0]
    assert target == ("127.0.0.1", 9998)
    deserialized = datamesh_pb2.TelemetryPacket()
    deserialized.ParseFromString(raw_bytes)
    assert deserialized.device_id == "ac-rack-01"
    assert deserialized.device_type == datamesh_pb2.AIR_CONDITIONER


def test_handle_discovery_request_updates_gateway_and_announces(
    fake_socket: FakeUDPSocket,
) -> None:
    # Arrange
    device = AirConditionerDevice(
        device_id="ac-rack-01",
        grpc_port=50051,
        socket_factory=lambda: fake_socket,
    )
    discovery = datamesh_pb2.DiscoveryRequest(
        gateway_ip="192.168.1.100",
        telemetry_udp_port=9998,
    )

    # Act
    device.handle_discovery_request(discovery.SerializeToString())

    # Assert
    assert device.gateway_host == "192.168.1.100"
    assert device.gateway_port == 9998
    assert len(fake_socket.sent_packets) == 1
    raw_bytes, target = fake_socket.sent_packets[0]
    assert target == ("192.168.1.100", 9998)
    announcement = datamesh_pb2.DeviceInfo()
    announcement.ParseFromString(raw_bytes)
    assert announcement.device_id == "ac-rack-01"
    assert announcement.grpc_port == 50051
    assert announcement.device_type == datamesh_pb2.AIR_CONDITIONER


def test_send_initial_registration_without_gateway_is_noop(
    fake_socket: FakeUDPSocket,
) -> None:
    # Arrange
    device = AirConditionerDevice(
        device_id="ac-rack-01",
        gateway_host=None,
        gateway_port=None,
        socket_factory=lambda: fake_socket,
    )

    # Act
    device.send_initial_registration()

    # Assert
    assert len(fake_socket.sent_packets) == 0


def test_handle_discovery_request_corrupted_payload(fake_socket: FakeUDPSocket) -> None:
    # Arrange
    device = AirConditionerDevice(
        device_id="ac-rack-01",
        socket_factory=lambda: fake_socket,
    )

    # Act
    device.handle_discovery_request(b"\xff\xff\xff\xff")

    # Assert
    assert len(fake_socket.sent_packets) == 0


def test_send_telemetry_without_gateway_returns_none(fake_socket: FakeUDPSocket) -> None:
    # Arrange
    device = AirConditionerDevice(
        device_id="ac-rack-01",
        gateway_host=None,
        gateway_port=None,
        socket_factory=lambda: fake_socket,
    )

    # Act
    packet = device.send_telemetry()

    # Assert
    assert packet is None
    assert len(fake_socket.sent_packets) == 0


def test_grpc_real_network_call_via_proxy() -> None:
    # Arrange: find free port for gRPC server
    with socket.socket() as s:
        s.bind(("", 0))
        free_port = s.getsockname()[1]

    device = AirConditionerDevice(
        device_id="ac-rack-02",
        grpc_port=free_port,
        advertised_ip="127.0.0.1",
    )
    device.start_grpc_server()
    proxy = GrpcACControlProxy(timeout_seconds=2.0)

    try:
        cmd = datamesh_pb2.ACControlRequest(
            device_id="ac-rack-02",
            power_on=True,
            target_temp_c=18.0,
            fan_speed_pct=90,
        )
        # Act
        resp = proxy.send_ac_control(device.to_device_info(), cmd)

        # Assert
        assert resp.success is True
        assert device.target_temp_c == 18.0
        assert device.fan_speed_pct == 90
    finally:
        device.stop()


def test_background_telemetry_streaming(fake_socket: FakeUDPSocket) -> None:
    # Arrange
    device = AirConditionerDevice(
        device_id="ac-rack-01",
        gateway_host="127.0.0.1",
        gateway_port=9998,
        send_interval_sec=0.05,
        socket_factory=lambda: fake_socket,
    )

    # Act
    device.start()
    time.sleep(0.12)
    device.stop()

    # Assert: at least 1 registration packet + 1 telemetry packet sent
    assert len(fake_socket.sent_packets) >= 2


def test_multicast_listener_bind_failure_fallback() -> None:
    # Arrange: invalid port causes bind failure
    device = AirConditionerDevice(
        device_id="ac-rack-01",
        multicast_port=-99,
    )

    # Act & Assert: does not raise, falls back gracefully
    device.start_multicast_listener()
    assert device._mcast_sock is None


def test_ac_main_load_config_and_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    import threading

    from sources.ac.main import _load_config, _setup_signals

    monkeypatch.setenv("AC_DEVICE_ID", "ac-custom-01")
    monkeypatch.setenv("AC_GRPC_PORT", "50099")
    monkeypatch.setenv("AC_ADVERTISED_IP", "10.0.0.5")
    monkeypatch.setenv("GATEWAY_HOST", "10.0.0.1")
    monkeypatch.setenv("GATEWAY_PORT", "9900")
    monkeypatch.setenv("SEND_INTERVAL_SEC", "2.5")
    monkeypatch.setenv("MULTICAST_GROUP", "239.255.0.2")
    monkeypatch.setenv("MULTICAST_PORT", "9990")

    # Act
    cfg = _load_config()

    # Assert
    assert cfg[0] == "ac-custom-01"
    assert cfg[1] == 50099
    assert cfg[2] == "10.0.0.5"
    assert cfg[3] == "10.0.0.1"
    assert cfg[4] == 9900
    assert abs(cfg[5] - 2.5) < 1e-4
    assert cfg[6] == "239.255.0.2"
    assert cfg[7] == 9990

    device = AirConditionerDevice(device_id="ac-custom-01")
    stop_event = threading.Event()
    _setup_signals(device, stop_event, "ac-custom-01")


def test_ac_main_waits_for_discovery_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    from sources.ac.main import _load_config

    monkeypatch.delenv("GATEWAY_HOST", raising=False)
    monkeypatch.delenv("AC_ADVERTISED_IP", raising=False)

    # Act
    cfg = _load_config()

    # Assert
    assert cfg[2] == ""
    assert cfg[3] == ""
