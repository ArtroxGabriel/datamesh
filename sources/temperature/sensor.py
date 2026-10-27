"""Rack Temperature Sensor source with continuous UDP streaming and immediate anomaly alerts."""

import logging
import math
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
# Hysteresis: alert only clears well below the trigger so sensor noise near 35 °C doesn't flap it.
ALERT_CLEAR_TEMP_C = 33.0
# Anomaly lifecycle: hot plateau (long enough to show on the dashboard), then exponential cooling.
DEFAULT_ANOMALY_HOLD_SEC = 20.0
DEFAULT_ANOMALY_DECAY_SEC = 10.0
MIN_ANOMALY_DECAY_SEC = 0.1
ANOMALY_SETTLED_EXCESS_C = 0.5
ANOMALY_NOISE_C = 0.4
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
        anomaly_hold_sec: float = DEFAULT_ANOMALY_HOLD_SEC,
        anomaly_decay_sec: float = DEFAULT_ANOMALY_DECAY_SEC,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.device_id = device_id
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.send_interval_sec = send_interval_sec
        self.multicast_group = multicast_group
        self.multicast_port = multicast_port
        self.base_temp_c = base_temp_c
        self.anomaly_hold_sec = anomaly_hold_sec
        self.anomaly_decay_sec = max(anomaly_decay_sec, MIN_ANOMALY_DECAY_SEC)
        self._clock: Callable[[], float] = clock or time.monotonic

        self._socket_factory: Callable[[], UDPSocketProtocol] = socket_factory or (
            lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        )
        self._sock: UDPSocketProtocol | None = None
        self._mcast_sock: socket.socket | None = None

        self._running = False
        # (peak_c, started_at) kept as one tuple so the signal handler swaps it atomically.
        self._anomaly: tuple[float, float] | None = None
        self._alert_active = False
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
        temperature = temp_c if temp_c is not None else self._simulate_temperature()
        return datamesh_pb2.TelemetryPacket(
            device_id=self.device_id,
            device_type=datamesh_pb2.TEMPERATURE_SENSOR,
            timestamp_ms=_now_ms(),
            is_alert=self._update_alert_state(temperature, forced=is_alert),
            temperature=datamesh_pb2.TemperatureTelemetry(temperature_c=temperature),
        )

    def _simulate_temperature(self) -> float:
        excess_c = self._anomaly_excess_c()
        if excess_c is None:
            return round(self.base_temp_c + random.uniform(-1.5, 2.5), 2)
        noise_c = random.uniform(-ANOMALY_NOISE_C, ANOMALY_NOISE_C)
        return round(self.base_temp_c + excess_c + noise_c, 2)

    def _anomaly_excess_c(self) -> float | None:
        """Heat above base: flat during the hold window, then decays exponentially to zero."""
        anomaly = self._anomaly
        if anomaly is None:
            return None
        peak_c, started_at = anomaly
        cooling_sec = self._clock() - started_at - self.anomaly_hold_sec
        excess_c = peak_c - self.base_temp_c
        if cooling_sec > 0:
            excess_c *= math.exp(-cooling_sec / self.anomaly_decay_sec)
        if excess_c >= ANOMALY_SETTLED_EXCESS_C:
            return excess_c
        if self._anomaly is anomaly:  # don't discard an anomaly re-triggered meanwhile
            self._anomaly = None
            logger.info("Anomaly on %s dissipated; back to nominal readings", self.device_id)
        return None

    def _update_alert_state(self, temperature: float, forced: bool) -> bool:
        if forced or temperature >= ALERT_THRESHOLD_TEMP_C:
            self._alert_active = True
        elif temperature < ALERT_CLEAR_TEMP_C:
            self._alert_active = False
        return self._alert_active

    def trigger_anomaly(self, temp_c: float = 38.5) -> datamesh_pb2.TelemetryPacket:
        """Immediately transmits a critical thermal anomaly alert packet (>35°C).

        The rack then stays hot for `anomaly_hold_sec` and cools back to its base temperature.

        Example:
            alert = sensor.trigger_anomaly(temp_c=39.0)
        """
        self._anomaly = (temp_c, self._clock())
        alert_packet = self.create_reading(temp_c=temp_c, is_alert=True)
        self.send_telemetry(alert_packet)
        logger.warning(
            "CRITICAL ALERT SENT: Device %s reached %.1f °C (hold %.0fs, then cooling)",
            self.device_id,
            alert_packet.temperature.temperature_c,
            self.anomaly_hold_sec,
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
        if hasattr(socket, "SO_REUSEPORT"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        try:
            sock.bind(("", self.multicast_port))
            mreq = struct.pack(
                "4sl",
                socket.inet_aton(self.multicast_group),
                socket.INADDR_ANY,
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            # Also join group on loopback (127.0.0.1) so discovery is robust on local runs
            try:
                mreq_lo = struct.pack(
                    "4s4s",
                    socket.inet_aton(self.multicast_group),
                    socket.inet_aton("127.0.0.1"),
                )
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq_lo)
            except Exception:
                pass
            sock.settimeout(SOCKET_TIMEOUT_SEC)
            self._mcast_sock = sock
            self._running = True

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
