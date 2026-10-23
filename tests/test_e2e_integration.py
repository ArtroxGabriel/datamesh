"""End-to-end integration test across Gateway, Sources, TCP Client, and FastAPI."""

import socket
import time

from fastapi.testclient import TestClient

from client.app import create_app
from client.gateway_client import TCPGatewayClient
from gateway.main import GatewayApp
from sources.ac.actuator import AirConditionerDevice
from sources.temperature.sensor import TemperatureSensor


def _get_free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_full_pipeline_telemetry_anomaly_actuation_and_analytics() -> None:
    # Arrange: start Gateway on ephemeral TCP and UDP ports
    udp_port = _get_free_udp_port()
    mcast_port = _get_free_udp_port()
    gw = GatewayApp(
        host="127.0.0.1",
        tcp_port=0,
        udp_port=udp_port,
        multicast_port=mcast_port,
        db_path=":memory:",
    )
    gw.start()
    assert gw.coordinator._tcp_server_sock is not None
    tcp_port = int(gw.coordinator._tcp_server_sock.getsockname()[1])

    ac = AirConditionerDevice(
        device_id="ac-e2e-01",
        grpc_port=0,
        advertised_ip="127.0.0.1",
        gateway_host="127.0.0.1",
        gateway_port=udp_port,
        send_interval_sec=0.1,
        multicast_port=mcast_port,
    )
    sensor = TemperatureSensor(
        device_id="temp-e2e-01",
        gateway_host="127.0.0.1",
        gateway_port=udp_port,
        send_interval_sec=0.1,
        multicast_port=mcast_port,
    )

    try:
        ac.start_grpc_server()
        ac.start()
        sensor.start()

        # Trigger immediate anomaly alert (> 35 C)
        sensor.trigger_anomaly(temp_c=39.2)

        # Wait briefly for UDP packets to be ingested into Gateway SQLite
        deadline = time.time() + 2.0
        tcp_client = TCPGatewayClient(host="127.0.0.1", port=tcp_port)
        while time.time() < deadline:
            if len(tcp_client.list_devices()) >= 2 and len(tcp_client.get_history(10)) >= 2:
                break
            time.sleep(0.05)

        web = TestClient(create_app(gateway_client=tcp_client))

        # Act & Assert 1: Devices listed via HTTP -> TCP -> Gateway
        devices_resp = web.get("/api/devices")
        assert devices_resp.status_code == 200
        device_ids = {d["device_id"] for d in devices_resp.json()}
        assert {"ac-e2e-01", "temp-e2e-01"}.issubset(device_ids)

        # Act & Assert 2: Actuate AC via HTTP -> TCP -> Gateway -> gRPC -> AC
        ctrl_resp = web.post(
            "/api/ac/control",
            json={
                "device_id": "ac-e2e-01",
                "power_on": True,
                "target_temp_c": 18.5,
                "fan_speed_pct": 90,
            },
        )
        assert ctrl_resp.status_code == 200
        assert ctrl_resp.json()["success"] is True
        assert ac.target_temp_c == 18.5
        assert ac.fan_speed_pct == 90

        # Act & Assert 3: Analytical query identifies the 39.2 C anomaly peak
        hot_resp = web.get("/api/analytics/hottest_rack?window_seconds=300")
        assert hot_resp.status_code == 200
        assert hot_resp.json()["target_device_id"] == "temp-e2e-01"
        assert hot_resp.json()["primary_value"] >= 39.2
    finally:
        sensor.stop()
        ac.stop()
        gw.stop()
