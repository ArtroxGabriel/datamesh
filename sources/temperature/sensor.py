"""Rack Temperature Sensor source with continuous UDP streaming and immediate anomaly alerts."""

import logging
import random
import socket
import struct
import threading
import time
from collections.abc import Callable
from typing import Protocol

import datamesh_pb2

logger = logging.getLogger(__name__)

DEFAULT_BASE_TEMP_C = 23.5
ALERT_THRESHOLD_TEMP_C = 35.0
DEFAULT_INTERVAL_SECONDS = 3.0
DEFAULT_MULTICAST_GROUP = "239.255.0.1"
DEFAULT_MULTICAST_PORT = 9999
SOCKET_TIMEOUT_SEC = 0.5


class UDPSocketProtocol(Protocol):
    """Protocol for sending UDP datagrams."""

    def sendto(self, data: bytes, target: tuple[str, int], /) -> int: ...
    def close(self) -> None: ...


def _now_ms() -> int:
    return int(time.time() * 1000)


class TemperatureSensor:
    """Simulates a rack temperature sensor emitting periodic telemetry
    and immediate threshold alerts.
    """

    def __init__(
        self,
        device_id: str = "temp-rack-01",
        gateway_host: str | None = None,
        gateway_port: int | None = None,
        send_interval_sec: float = DEFAULT_INTERVAL_SECONDS,
        multicast_group: str = DEFAULT_MULTICAST_GROUP,
        multicast_port: int = DEFAULT_MULTICAST_PORT,
        base_temp_c: float = DEFAULT_BASE_TEMP_C,
        socket_factory: Callable[[], UDPSocketProtocol] | None = None,
    ) -> None:
        self.device_id = device_id
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.send_interval_sec = send_interval_sec
        self.multicast_group = multicast_group
        self.multicast_port = multicast_port
        self.base_temp_c = base_temp_c

        self._socket_factory: Callable[[], UDPSocketProtocol] = socket_factory or (
            lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        )
        self._sock: UDPSocketProtocol | None = None
        self._mcast_sock: socket.socket | None = None

        self._running = False
        self._lock = threading.Lock()
        self._stream_thread: threading.Thread | None = None
        self._mcast_thread: threading.Thread | None = None

    def create_reading(
        self, temp_c: float | None = None, is_alert: bool = False
    ) -> datamesh_pb2.TelemetryPacket:
        """Constructs a TelemetryPacket with the specified or simulated temperature.

        Example:
            packet = sensor.create_reading(temp_c=24.0)
        """
        temperature = (
            temp_c if temp_c is not None else round(self.base_temp_c + random.uniform(-1.5, 2.5), 2)
        )
        alert_flag = is_alert or (temperature >= ALERT_THRESHOLD_TEMP_C)
        return datamesh_pb2.TelemetryPacket(
            device_id=self.device_id,
            device_type=datamesh_pb2.TEMPERATURE_SENSOR,
            timestamp_ms=_now_ms(),
            is_alert=alert_flag,
            temperature_c=temperature,
        )

    def trigger_anomaly(self, temp_c: float = 38.5) -> datamesh_pb2.TelemetryPacket:
        """Immediately transmits a critical thermal anomaly alert packet (>35°C).

        Example:
            alert = sensor.trigger_anomaly(temp_c=39.0)
        """
        alert_packet = self.create_reading(temp_c=temp_c, is_alert=True)
        self.send_telemetry(alert_packet)
        logger.warning(
            "CRITICAL ALERT SENT: Device %s reached %.1f °C",
            self.device_id,
            alert_packet.temperature_c,
        )
        return alert_packet

    def send_telemetry(self, packet: datamesh_pb2.TelemetryPacket) -> None:
        """Encodes and transmits a TelemetryPacket via UDP unicast to the Gateway.

        Example:
            sensor.send_telemetry(packet)
        """
        with self._lock:
            if not self.gateway_host or not self.gateway_port:
                return
            if not self._sock:
                self._sock = self._socket_factory()

            payload = packet.SerializeToString()
            self._sock.sendto(payload, (self.gateway_host, self.gateway_port))

    def handle_discovery_request(self, raw_bytes: bytes) -> None:
        """Learns Gateway endpoint from discovery beacon and sends DeviceInfo response.

        Example:
            sensor.handle_discovery_request(beacon_bytes)
        """
        req = datamesh_pb2.DiscoveryRequest()
        try:
            req.ParseFromString(raw_bytes)
        except Exception as err:
            logger.warning("Failed to parse discovery request: %s", err)
            return

        with self._lock:
            self.gateway_host = req.gateway_ip
            self.gateway_port = req.telemetry_udp_port
            if not self._sock:
                self._sock = self._socket_factory()

            announcement = datamesh_pb2.DeviceInfo(
                device_id=self.device_id,
                device_type=datamesh_pb2.TEMPERATURE_SENSOR,
                is_online=True,
                last_seen_ms=_now_ms(),
                state_summary=f"Online | Base temp ~{self.base_temp_c:.1f} °C",
            )
            self._sock.sendto(
                announcement.SerializeToString(),
                (self.gateway_host, self.gateway_port),
            )
        logger.info(
            "Learned gateway at %s:%d and sent announcement",
            req.gateway_ip,
            req.telemetry_udp_port,
        )

    def start_multicast_listener(self) -> None:
        """Binds and joins the multicast discovery group to listen for Gateway beacons.

        Example:
            sensor.start_multicast_listener()
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", self.multicast_port))
            mreq = struct.pack(
                "4sl",
                socket.inet_aton(self.multicast_group),
                socket.INADDR_ANY,
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(SOCKET_TIMEOUT_SEC)
            self._mcast_sock = sock

            self._mcast_thread = threading.Thread(
                target=self._multicast_listen_loop,
                daemon=True,
                name="temp-sensor-mcast",
            )
            self._mcast_thread.start()
            logger.info(
                "Listening for discovery beacons on %s:%d",
                self.multicast_group,
                self.multicast_port,
            )
        except Exception as err:
            logger.warning(
                "Could not bind multicast socket (%s). Using static gateway endpoint.", err
            )

    def _multicast_listen_loop(self) -> None:
        while self._running and self._mcast_sock:
            try:
                data, _ = self._mcast_sock.recvfrom(2048)
                self.handle_discovery_request(data)
            except TimeoutError:
                continue
            except OSError:
                break

    def start(self) -> None:
        """Starts periodic telemetry streaming and multicast listening threads.

        Example:
            sensor.start()
        """
        self._running = True
        if not self._sock:
            self._sock = self._socket_factory()

        self._stream_thread = threading.Thread(
            target=self._stream_loop, daemon=True, name="temp-sensor-stream"
        )
        self._stream_thread.start()

    def _stream_loop(self) -> None:
        while self._running:
            packet = self.create_reading()
            self.send_telemetry(packet)
            time.sleep(self.send_interval_sec)

    def stop(self) -> None:
        """Stops background threads and closes sockets.

        Example:
            sensor.stop()
        """
        self._running = False
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
            if self._mcast_sock:
                try:
                    self._mcast_sock.close()
                except Exception:
                    pass
                self._mcast_sock = None
