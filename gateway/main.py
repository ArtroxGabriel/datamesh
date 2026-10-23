"""Main entrypoint for DataMesh DCIM Gateway service."""

import logging
import os
import signal
import socket
import sys
import threading
import time

from gateway.proxy import GrpcACControlProxy
from gateway.registry import DeviceRegistry
from gateway.service import GatewayCoordinator
from gateway.storage import TelemetryStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gateway")

UDP_BUFFER_SIZE = 65535
BEACON_INTERVAL_SECONDS = 5.0
DEFAULT_SOCKET_TIMEOUT_SEC = 0.5
DEFAULT_TCP_PORT = 9997
DEFAULT_UDP_PORT = 9998
DEFAULT_MULTICAST_PORT = 9999


class GatewayApp:
    """Manages lifecycle of all Gateway background servers and beacons."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        tcp_port: int = DEFAULT_TCP_PORT,
        udp_port: int = DEFAULT_UDP_PORT,
        multicast_group: str = "239.255.0.1",
        multicast_port: int = DEFAULT_MULTICAST_PORT,
        db_path: str = "datamesh.db",
        advertised_ip: str | None = None,
    ) -> None:
        self.host = host
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.multicast_group = multicast_group
        self.multicast_port = multicast_port
        self.advertised_ip = advertised_ip or ("127.0.0.1" if host == "0.0.0.0" else host)

        self.storage = TelemetryStorage(db_path)
        self.registry = DeviceRegistry()
        self.ac_proxy = GrpcACControlProxy()
        self.coordinator = GatewayCoordinator(
            storage=self.storage,
            registry=self.registry,
            ac_proxy=self.ac_proxy,
        )

        self._running = False
        self._udp_sock: socket.socket | None = None
        self._udp_thread: threading.Thread | None = None
        self._beacon_thread: threading.Thread | None = None

    def start(self) -> None:
        """Starts TCP server, UDP ingestion receiver, and multicast beacon loop.

        Example:
            app.start()
        """
        self._running = True
        bound_tcp_port = self.coordinator.start_tcp_server(self.host, self.tcp_port)
        logger.info("TCP Server listening on %s:%d", self.host, bound_tcp_port)

        self._start_udp_server()
        self._start_beacon_loop()
        logger.info("Gateway service initialized successfully.")

    def _start_udp_server(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.udp_port))
        sock.settimeout(DEFAULT_SOCKET_TIMEOUT_SEC)
        self._udp_sock = sock

        self._udp_thread = threading.Thread(
            target=self._udp_receive_loop, daemon=True, name="gateway-udp-ingest"
        )
        self._udp_thread.start()
        logger.info("UDP Telemetry Ingestion listening on %s:%d", self.host, self.udp_port)

    def _udp_receive_loop(self) -> None:
        while self._running and self._udp_sock:
            try:
                data, addr = self._udp_sock.recvfrom(UDP_BUFFER_SIZE)
                self.coordinator.handle_udp_datagram(data, addr)
            except TimeoutError:
                continue
            except OSError:
                break

    def _start_beacon_loop(self) -> None:
        self._beacon_thread = threading.Thread(
            target=self._beacon_worker, daemon=True, name="gateway-multicast-beacon"
        )
        self._beacon_thread.start()

    def _beacon_worker(self) -> None:
        while self._running:
            try:
                self.coordinator.send_discovery_beacon(
                    multicast_group=self.multicast_group,
                    multicast_port=self.multicast_port,
                    gateway_ip=self.advertised_ip,
                    udp_port=self.udp_port,
                )
            except Exception as err:
                logger.warning("Failed to broadcast multicast beacon: %s", err)
            time.sleep(BEACON_INTERVAL_SECONDS)

    def stop(self) -> None:
        """Gracefully shuts down all listeners and connections.

        Example:
            app.stop()
        """
        self._running = False
        self.coordinator.stop_tcp_server()
        if self._udp_sock:
            try:
                self._udp_sock.close()
            except Exception:
                pass
            self._udp_sock = None
        self.storage.close()
        logger.info("Gateway service stopped.")


def main() -> None:
    host = os.getenv("GATEWAY_HOST", "0.0.0.0")
    tcp_port = int(os.getenv("GATEWAY_TCP_PORT", str(DEFAULT_TCP_PORT)))
    udp_port = int(os.getenv("TELEMETRY_UDP_PORT", str(DEFAULT_UDP_PORT)))
    multicast_group = os.getenv("MULTICAST_GROUP", "239.255.0.1")
    multicast_port = int(os.getenv("MULTICAST_PORT", str(DEFAULT_MULTICAST_PORT)))
    db_path = os.getenv("DB_PATH", "datamesh.db")

    app = GatewayApp(
        host=host,
        tcp_port=tcp_port,
        udp_port=udp_port,
        multicast_group=multicast_group,
        multicast_port=multicast_port,
        db_path=db_path,
    )

    def _shutdown(_sig: int, _frame: object) -> None:
        logger.info("Termination signal received. Exiting...")
        app.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    app.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        app.stop()


if __name__ == "__main__":
    main()
