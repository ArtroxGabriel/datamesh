"""Executable entrypoint for Precision Air Conditioner actuator source."""

import logging
import os
import signal
import sys
import threading
import time

from sources.ac.actuator import AirConditionerDevice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ac-actuator")


def _load_config() -> tuple[str, int, str, str, int, float, str, int]:
    device_id = os.getenv("AC_DEVICE_ID", "ac-rack-01")
    grpc_port = int(os.getenv("AC_GRPC_PORT", "50051"))
    # Empty IP lets the Gateway use the address the announcement came from.
    adv_ip = os.getenv("AC_ADVERTISED_IP", "")
    # Empty host makes the AC wait for a discovery beacon before streaming.
    gateway_host = os.getenv("GATEWAY_HOST", "")
    gateway_port = int(os.getenv("GATEWAY_PORT", "9998"))
    interval_sec = float(os.getenv("SEND_INTERVAL_SEC", "5.0"))
    mcast_group = os.getenv("MULTICAST_GROUP", "239.255.0.1")
    mcast_port = int(os.getenv("MULTICAST_PORT", "9999"))
    return (
        device_id,
        grpc_port,
        adv_ip,
        gateway_host,
        gateway_port,
        interval_sec,
        mcast_group,
        mcast_port,
    )


def _setup_signals(
    device: AirConditionerDevice,
    stop_event: threading.Event,
    device_id: str,
) -> None:
    def _shutdown(_sig: int, _frame: object) -> None:
        logger.info("Shutdown signal received for %s. Stopping...", device_id)
        stop_event.set()
        device.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)


def main() -> None:
    cfg = _load_config()
    device = AirConditionerDevice(
        device_id=cfg[0],
        grpc_port=cfg[1],
        advertised_ip=cfg[2],
        gateway_host=cfg[3],
        gateway_port=cfg[4],
        send_interval_sec=cfg[5],
        multicast_group=cfg[6],
        multicast_port=cfg[7],
    )
    stop_event = threading.Event()
    _setup_signals(device, stop_event, cfg[0])

    device.start_grpc_server()
    device.start_multicast_listener()
    device.start()
    target_desc = f"{cfg[3]}:{cfg[4]}" if cfg[3] else "awaiting multicast beacon"
    logger.info("AC %s active (gRPC :%d, target: %s)", cfg[0], cfg[1], target_desc)

    while not stop_event.is_set():
        time.sleep(1.0)


if __name__ == "__main__":
    main()
