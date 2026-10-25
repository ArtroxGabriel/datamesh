"""FastAPI Web application backend for DataMesh DCIM dashboard."""

from pathlib import Path
from typing import Any

import datamesh_pb2
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from client.events import Event, EventTimeline
from client.gateway_client import (
    DEFAULT_GATEWAY_HOST,
    DEFAULT_GATEWAY_PORT,
    GatewayClientProtocol,
    TCPGatewayClient,
)

STATIC_DIR = Path(__file__).parent / "static"


class ACControlBody(BaseModel):
    """Payload schema for Precision AC actuation commands."""

    device_id: str = Field(..., description="Target AC unit ID")
    power_on: bool = Field(True, description="AC Power switch")
    target_temp_c: float = Field(21.0, description="Target temperature setpoint")
    fan_speed_pct: int = Field(50, description="Fan speed percentage (0-100)")


def _device_to_dict(d: datamesh_pb2.DeviceInfo) -> dict[str, Any]:
    type_name = datamesh_pb2.DeviceType.Name(d.device_type)
    return {
        "device_id": d.device_id,
        "device_type": type_name,
        "ip": d.ip,
        "grpc_port": d.grpc_port,
        "is_online": d.is_online,
        "state_summary": d.state_summary,
        "last_seen_ms": d.last_seen_ms,
    }


def _telemetry_to_dict(t: datamesh_pb2.TelemetryPacket) -> dict[str, Any]:
    type_name = datamesh_pb2.DeviceType.Name(t.device_type)
    return {
        "device_id": t.device_id,
        "device_type": type_name,
        "timestamp_ms": t.timestamp_ms,
        "is_alert": t.is_alert,
        "temperature_c": t.temperature_c,
        "target_temp_c": t.target_temp_c,
        "fan_speed_pct": t.fan_speed_pct,
        "power_watts": t.power_watts,
        "current_amps": t.current_amps,
        "voltage_volts": t.voltage_volts,
        "ac_power_on": t.ac_power_on,
    }


def _analytics_to_dict(a: datamesh_pb2.AnalyticsResult) -> dict[str, Any]:
    type_name = datamesh_pb2.AnalyticsQueryType.Name(a.query_type)
    return {
        "query_type": type_name,
        "target_device_id": a.target_device_id,
        "primary_value": a.primary_value,
        "secondary_value": a.secondary_value,
        "unit": a.unit,
        "summary": a.summary,
        "sample_count": a.sample_count,
    }


def _event_to_dict(e: Event) -> dict[str, Any]:
    return {
        "timestamp_ms": e.timestamp_ms,
        "category": e.category,
        "severity": e.severity,
        "device_id": e.device_id,
        "message": e.message,
    }


def _serve_static_page(name: str) -> Any:
    page = STATIC_DIR / name
    if page.exists():
        return FileResponse(page)
    return HTMLResponse(f"<h2>DataMesh DCIM</h2><p>Static page '{name}' not found.</p>")


def _parse_query_type(raw_type: str) -> datamesh_pb2.AnalyticsQueryType:
    normalized = raw_type.upper().strip()
    mapping = {
        "HOTTEST_RACK": datamesh_pb2.HOTTEST_RACK,
        "AVG_PDU_POWER": datamesh_pb2.AVG_PDU_POWER,
        "THERMAL_STABILITY": datamesh_pb2.THERMAL_STABILITY,
    }
    if normalized not in mapping:
        raise HTTPException(
            status_code=400,
            detail=f"Unrecognized query_type: '{raw_type}'. Supported: {list(mapping.keys())}",
        )
    return mapping[normalized]


def create_app(
    gateway_client: GatewayClientProtocol | None = None,
    timeline: EventTimeline | None = None,
) -> FastAPI:
    """Constructs and configures the FastAPI instance with route handlers and static assets.

    Example:
        app = create_app()
    """
    client = gateway_client or TCPGatewayClient(
        host=DEFAULT_GATEWAY_HOST, port=DEFAULT_GATEWAY_PORT
    )
    events = timeline or EventTimeline()
    app = FastAPI(title="DataMesh DCIM Client", version="1.0.0")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def serve_dashboard() -> Any:
        return _serve_static_page("index.html")

    @app.get("/events", response_class=HTMLResponse)
    def serve_events_page() -> Any:
        return _serve_static_page("events.html")

    @app.get("/api/events")
    def get_events(limit: int = Query(default=200, ge=1, le=500)) -> list[dict[str, Any]]:
        return [_event_to_dict(e) for e in events.recent(limit)]

    @app.get("/api/devices")
    def get_devices() -> list[dict[str, Any]]:
        devices = client.list_devices()
        return [_device_to_dict(d) for d in devices]

    @app.get("/api/telemetry/history")
    def get_telemetry_history(
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        history = client.get_history(limit=limit)
        return [_telemetry_to_dict(t) for t in history]

    @app.post("/api/ac/control")
    def control_ac(body: ACControlBody) -> dict[str, Any]:
        success, message = client.control_ac(
            device_id=body.device_id,
            power_on=body.power_on,
            target_temp_c=body.target_temp_c,
            fan_speed_pct=body.fan_speed_pct,
        )
        command = datamesh_pb2.ACControlRequest(**body.model_dump())
        events.record_ac_command(command, success, message)
        return {"success": success, "message": message}

    @app.get("/api/analytics/{query_type}")
    def get_analytics(
        query_type: str,
        window_seconds: int = Query(default=300, ge=10, le=86400),
    ) -> dict[str, Any]:
        q_enum = _parse_query_type(query_type)
        res = client.query_analytics(query_type=q_enum, window_seconds=window_seconds)
        events.record_analytics(res)
        return _analytics_to_dict(res)

    return app
