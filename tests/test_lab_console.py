import datamesh_pb2
from fastapi.testclient import TestClient

from common.security import SecurityError
from gateway.service import GatewayCoordinator
from gateway.storage import TelemetryStorage
from lab import controller
from sources.temperature.main import create_lab_control_app
from sources.temperature.sensor import TemperatureSensor


def test_gateway_security_rejection_is_available_in_tcp_response(monkeypatch):
    class Reject:
        def decode(self, _data):
            raise SecurityError("replay detected")

    coordinator = GatewayCoordinator(storage=TelemetryStorage(":memory:"))
    monkeypatch.setattr(coordinator, "_udp_security", Reject())
    try:
        coordinator.handle_udp_datagram(b"replay", ("127.0.0.1", 1234))
        result = coordinator.handle_client_request(
            datamesh_pb2.ClientRequest(action=datamesh_pb2.GET_SECURITY_EVENTS)
        )
        round_trip = datamesh_pb2.ClientResponse.FromString(result.SerializeToString())
        assert round_trip.security_mode == "secure"
        assert round_trip.security_events[0].message == "replay detected"
    finally:
        coordinator.close()


def test_anomaly_endpoint_requires_lab_token(monkeypatch):
    sensor = TemperatureSensor(device_id="temp-test")
    calls = []
    monkeypatch.setattr(sensor, "trigger_anomaly", lambda temp_c: calls.append(temp_c))
    app = create_lab_control_app(sensor, "secret")
    client = TestClient(app)
    assert client.post("/anomaly").status_code == 403
    assert calls == []
    assert client.post("/anomaly", headers={"X-Lab-Token": "secret"}).status_code == 200
    assert calls == [38.8]


def test_controller_only_accepts_fixed_scenarios_and_local_host(monkeypatch):
    monkeypatch.setattr(
        controller, "snapshot", lambda: {"ready": True, "security": {"mode": "secure"}}
    )
    calls = []
    monkeypatch.setattr(
        controller, "fetch", lambda url, body: calls.append((url, body)) or {"started": True}
    )
    client = TestClient(controller.app, base_url="http://localhost:8081")
    assert client.post("/api/run", json={"scenario": "other"}).status_code == 400
    result = client.post("/api/run", json={"scenario": "replay", "automatic": False})
    assert result.status_code == 200
    assert calls[0][1] == {"scenario": "replay", "automatic": False, "mode": "secure"}
    assert client.get("/api/state", headers={"Host": "example.org"}).status_code == 403
    assert (
        client.post(
            "/api/run", headers={"Origin": "https://example.org"}, json={"scenario": "sniff"}
        ).status_code
        == 403
    )
