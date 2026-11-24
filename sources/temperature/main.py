"""Executable entrypoint for Rack Temperature Sensor source."""

import hmac
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, HTTPException

if hasattr(signal, "SIGUSR1"):
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

from sources.temperature.sensor import (
    DEFAULT_ANOMALY_DECAY_SEC,
    DEFAULT_ANOMALY_HOLD_SEC,
    TemperatureSensor,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("temp-sensor")


def _interactive_anomaly_trigger(sensor: TemperatureSensor, stop_event: threading.Event) -> None:
    logger.info("=================================================================")
    logger.info("INTERACTIVE DEMO: Press [ENTER] to trigger immediate anomaly alert")
    logger.info("thermal threshold exceeded (> 35°C) to the Gateway.")
    logger.info("=================================================================")
    while not stop_event.is_set():
        try:
            # sys.stdin.readline is blocking, but won't crash when running headlessly
            line = sys.stdin.readline()
            if not line:
                break
            sensor.trigger_anomaly(temp_c=38.8)
        except Exception:
            break


def _load_config() -> tuple[str, str | None, int | None, float, str, int, float]:
    sensor_id = os.getenv("SENSOR_ID", "temp-rack-01")
    # Empty by default, so the sensor waits for a discovery beacon before streaming.
    raw_host = os.getenv("GATEWAY_HOST", "")
    gateway_host = raw_host if raw_host else None
    raw_port = int(os.getenv("GATEWAY_PORT", "9998"))
    gateway_port = raw_port if raw_port > 0 else None
    interval_sec = float(os.getenv("SEND_INTERVAL_SEC", "3.0"))
    mcast_group = os.getenv("MULTICAST_GROUP", "239.255.0.1")
    mcast_port = int(os.getenv("MULTICAST_PORT", "9999"))
    base_temp_c = float(os.getenv("BASE_TEMP_C", "23.5"))
    return sensor_id, gateway_host, gateway_port, interval_sec, mcast_group, mcast_port, base_temp_c


def _load_anomaly_timing() -> tuple[float, float]:
    hold_sec = float(os.getenv("ANOMALY_HOLD_SEC", str(DEFAULT_ANOMALY_HOLD_SEC)))
    decay_sec = float(os.getenv("ANOMALY_DECAY_SEC", str(DEFAULT_ANOMALY_DECAY_SEC)))
    return hold_sec, decay_sec


def _setup_signals(sensor: TemperatureSensor, stop_event: threading.Event, sensor_id: str) -> None:
    def _shutdown(_sig: int, _frame: object) -> None:
        logger.info("Shutdown signal received for %s. Stopping...", sensor_id)
        stop_event.set()
        sensor.stop()
        sys.exit(0)

    def _on_usr1(_sig: int, _frame: object) -> None:
        sensor.trigger_anomaly(temp_c=38.8)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, _on_usr1)


def create_lab_control_app(sensor: TemperatureSensor, token: str) -> FastAPI:
    """Expose only the simulated anomaly trigger to holders of the lab token."""
    if not token:
        raise ValueError("Lab token is empty")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/anomaly")
    def anomaly(x_lab_token: str = Header(default="")) -> dict[str, str]:
        if not hmac.compare_digest(x_lab_token, token):
            raise HTTPException(status_code=403, detail="forbidden")
        sensor.trigger_anomaly(temp_c=38.8)
        return {"device_id": sensor.device_id, "status": "triggered"}

    return app


def start_lab_control(sensor: TemperatureSensor) -> None:
    """Start the optional token-protected anomaly endpoint for the isolated lab."""
    token_path = os.getenv("DATAMESH_LAB_TOKEN_FILE")
    if not token_path:
        return
    app = create_lab_control_app(sensor, Path(token_path).read_text().strip())
    server = threading.Thread(
        target=uvicorn.run,
        kwargs={"app": app, "host": "0.0.0.0", "port": 8092, "log_level": "warning"},
        daemon=True,
        name="lab-anomaly-control",
    )
    server.start()


def main() -> None:
    s_id, gw_host, gw_port, interval, mc_grp, mc_port, base_temp = _load_config()
    hold_sec, decay_sec = _load_anomaly_timing()
    sensor = TemperatureSensor(
        device_id=s_id,
        gateway_host=gw_host,
        gateway_port=gw_port,
        send_interval_sec=interval,
        multicast_group=mc_grp,
        multicast_port=mc_port,
        base_temp_c=base_temp,
        anomaly_hold_sec=hold_sec,
        anomaly_decay_sec=decay_sec,
    )
    stop_event = threading.Event()
    _setup_signals(sensor, stop_event, s_id)

    start_lab_control(sensor)
    sensor.start_multicast_listener()
    sensor.start()
    target_desc = f"{gw_host}:{gw_port}" if gw_host and gw_port else "awaiting multicast beacon"
    logger.info("Sensor %s started. Target: %s (%.1fs)", s_id, target_desc, interval)

    trigger_thread = threading.Thread(
        target=_interactive_anomaly_trigger,
        args=(sensor, stop_event),
        daemon=True,
        name="anomaly-keyboard-trigger",
    )
    trigger_thread.start()

    while not stop_event.is_set():
        time.sleep(1.0)


if __name__ == "__main__":
    main()
