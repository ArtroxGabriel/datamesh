"""Unit tests for FastAPI Web Client backend."""

import datamesh_pb2
import pytest
from fastapi.testclient import TestClient

from client.app import create_app
from client.gateway_client import GatewayClientProtocol


class FakeGatewayClient(GatewayClientProtocol):
    """In-memory fake GatewayClient for deterministic FastAPI testing."""

    def __init__(self) -> None:
        self.devices: list[datamesh_pb2.DeviceInfo] = []
        self.history: list[datamesh_pb2.TelemetryPacket] = []
        self.last_ac_command: dict[str, object] | None = None
        self.ac_success = True
        self.ac_message = "AC updated"

    def list_devices(self) -> list[datamesh_pb2.DeviceInfo]:
        return list(self.devices)

    def control_ac(
        self,
        device_id: str,
        power_on: bool,
        target_temp_c: float,
        fan_speed_pct: int,
    ) -> tuple[bool, str]:
        self.last_ac_command = {
            "device_id": device_id,
            "power_on": power_on,
            "target_temp_c": target_temp_c,
            "fan_speed_pct": fan_speed_pct,
        }
        return self.ac_success, self.ac_message

    def get_history(self, limit: int = 100) -> list[datamesh_pb2.TelemetryPacket]:
        return list(self.history[:limit])

    def query_analytics(
        self,
        query_type: datamesh_pb2.AnalyticsQueryType,
        window_seconds: int = 300,
    ) -> datamesh_pb2.AnalyticsResult:
        if query_type == datamesh_pb2.HOTTEST_RACK:
            return datamesh_pb2.AnalyticsResult(
                query_type=query_type,
                target_device_id="temp-rack-01",
                primary_value=31.2,
                unit="°C",
                summary="Rack temp-rack-01 registrou pico de 31.2 °C",
                sample_count=10,
            )
        if query_type == datamesh_pb2.AVG_PDU_POWER:
            return datamesh_pb2.AnalyticsResult(
                query_type=query_type,
                primary_value=1420.5,
                unit="W",
                summary="Consumo médio das PDUs: 1420.5 W",
                sample_count=20,
            )
        return datamesh_pb2.AnalyticsResult(
            query_type=query_type,
            primary_value=0.45,
            unit="°C (std dev)",
            summary="Desvio padrão térmico: 0.45 °C",
            sample_count=15,
        )


@pytest.fixture
def fake_gateway() -> FakeGatewayClient:
    return FakeGatewayClient()


@pytest.fixture
def test_client(fake_gateway: FakeGatewayClient) -> TestClient:
    app = create_app(gateway_client=fake_gateway)
    return TestClient(app)


def test_get_devices_returns_json_list(
    test_client: TestClient, fake_gateway: FakeGatewayClient
) -> None:
    # Arrange
    fake_gateway.devices = [
        datamesh_pb2.DeviceInfo(
            device_id="temp-rack-01",
            device_type=datamesh_pb2.TEMPERATURE_SENSOR,
            ip="127.0.0.1",
            is_online=True,
            state_summary="23.8 °C",
            last_seen_ms=1000,
        ),
        datamesh_pb2.DeviceInfo(
            device_id="ac-rack-01",
            device_type=datamesh_pb2.AIR_CONDITIONER,
            ip="127.0.0.1",
            grpc_port=50051,
            is_online=False,
            state_summary="OFFLINE",
            last_seen_ms=500,
        ),
    ]

    # Act
    resp = test_client.get("/api/devices")

    # Assert
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["device_id"] == "temp-rack-01"
    assert data[0]["device_type"] == "TEMPERATURE_SENSOR"
    assert data[0]["is_online"] is True
    assert data[1]["device_id"] == "ac-rack-01"
    assert data[1]["is_online"] is False


def test_get_telemetry_history_returns_json_records(
    test_client: TestClient, fake_gateway: FakeGatewayClient
) -> None:
    # Arrange
    fake_gateway.history = [
        datamesh_pb2.TelemetryPacket(
            device_id="pdu-rack-01",
            device_type=datamesh_pb2.RACK_PDU,
            timestamp_ms=1700000000,
            power_watts=1450.0,
            current_amps=6.6,
            voltage_volts=220.0,
        )
    ]

    # Act
    resp = test_client.get("/api/telemetry/history?limit=10")

    # Assert
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) == 1
    assert records[0]["device_id"] == "pdu-rack-01"
    assert records[0]["power_watts"] == 1450.0
    assert records[0]["voltage_volts"] == 220.0


def test_post_ac_control_success(test_client: TestClient, fake_gateway: FakeGatewayClient) -> None:
    # Arrange & Act
    payload = {
        "device_id": "ac-rack-01",
        "power_on": True,
        "target_temp_c": 19.0,
        "fan_speed_pct": 80,
    }
    resp = test_client.post("/api/ac/control", json=payload)

    # Assert
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["message"] == "AC updated"
    assert fake_gateway.last_ac_command == payload


def test_post_ac_control_failure_propagation(
    test_client: TestClient, fake_gateway: FakeGatewayClient
) -> None:
    # Arrange
    fake_gateway.ac_success = False
    fake_gateway.ac_message = "AC unreachable"

    # Act
    payload = {
        "device_id": "ac-rack-01",
        "power_on": False,
        "target_temp_c": 22.0,
        "fan_speed_pct": 0,
    }
    resp = test_client.post("/api/ac/control", json=payload)

    # Assert
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "unreachable" in body["message"]


def test_get_analytics_queries(test_client: TestClient) -> None:
    # Act: Test all 3 analytical queries
    resp_hot = test_client.get("/api/analytics/hottest_rack?window_seconds=120")
    resp_pdu = test_client.get("/api/analytics/avg_pdu_power?window_seconds=300")
    resp_stab = test_client.get("/api/analytics/thermal_stability?window_seconds=600")

    # Assert
    assert resp_hot.status_code == 200
    assert resp_hot.json()["query_type"] == "HOTTEST_RACK"
    assert resp_hot.json()["target_device_id"] == "temp-rack-01"
    assert resp_hot.json()["primary_value"] == 31.2

    assert resp_pdu.status_code == 200
    assert resp_pdu.json()["query_type"] == "AVG_PDU_POWER"
    assert resp_pdu.json()["primary_value"] == 1420.5

    assert resp_stab.status_code == 200
    assert resp_stab.json()["query_type"] == "THERMAL_STABILITY"
    assert resp_stab.json()["primary_value"] == 0.45


def test_get_analytics_invalid_query_returns_400(test_client: TestClient) -> None:
    # Act
    resp = test_client.get("/api/analytics/invalid_query_type")

    # Assert
    assert resp.status_code == 400
    assert "unrecognized" in resp.json()["detail"].lower()


def test_main_load_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from client.main import _load_config

    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("WEB_PORT", "8888")
    monkeypatch.setenv("GATEWAY_HOST", "10.0.0.1")
    monkeypatch.setenv("GATEWAY_PORT", "9900")

    host, port, gw_host, gw_port = _load_config()
    assert host == "127.0.0.1"
    assert port == 8888
    assert gw_host == "10.0.0.1"
    assert gw_port == 9900


def test_serve_dashboard_returns_html(test_client: TestClient) -> None:
    # Act
    resp = test_client.get("/")

    # Assert
    assert resp.status_code == 200
    assert "DataMesh" in resp.text
    assert "text/html" in resp.headers["content-type"]
