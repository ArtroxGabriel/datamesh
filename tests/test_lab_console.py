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


def test_menu_endpoint_and_actions_on_port_8082(monkeypatch):
    docker_calls = []
    monkeypatch.setattr(
        controller, "docker_run", lambda *args, **_kw: docker_calls.append(args) or ""
    )
    monkeypatch.setattr(controller, "snapshot", lambda: {"security": {"mode": "secure"}})
    client = TestClient(controller.app, base_url="http://127.0.0.1:8082")
    assert "Menu Operacional" in client.get("/").text
    assert client.post("/api/action", json={"action": "unknown"}).status_code == 400
    assert (
        client.post("/api/action", json={"action": "stop_source", "target": "gateway"}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/action", json={"action": "add_source", "source_type": "temp", "target": "../bad"}
        ).status_code
        == 400
    )
    headers = {"Origin": "http://127.0.0.1:8082"}
    assert (
        client.post("/api/action", headers=headers, json={"action": "pdu_overload"}).status_code
        == 200
    )
    assert (
        client.post("/api/action", headers=headers, json={"action": "stack_up"}).status_code == 200
    )
    assert (
        client.post(
            "/api/action",
            headers=headers,
            json={"action": "add_source", "source_type": "temp", "target": "temp-02-curie"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/action",
            headers=headers,
            json={"action": "remove_source", "target": "temp-02-curie"},
        ).status_code
        == 200
    )
    assert any("USR1" in c and "pdu" in c for c in docker_calls)
    assert any("up" in c for c in docker_calls)
    assert any("datamesh-extra-temp-02-curie" in c and "run" in c for c in docker_calls)
    assert any("datamesh-extra-temp-02-curie" in c and "rm" in c for c in docker_calls)
    auto_resp = client.post(
        "/api/action",
        headers=headers,
        json={"action": "add_source", "source_type": "pdu", "param": "1850"},
    )
    assert auto_resp.status_code == 200
    assert auto_resp.json()["target"].startswith("pdu-02-")
    assert (
        client.post(
            "/api/action",
            headers=headers,
            json={"action": "anomaly", "target": "temp-01-turing"},
        ).status_code
        == 200
    )
    assert any("USR1" in c and "temperature" in c for c in docker_calls)
