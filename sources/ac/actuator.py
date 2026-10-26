"""Precision Air Conditioner actuator source with gRPC control and UDP telemetry."""

import logging
import random
import socket
import struct
import threading
import time
from collections.abc import Callable
from concurrent import futures
from typing import Protocol

import datamesh_pb2
import datamesh_pb2_grpc
import grpc

logger = logging.getLogger(__name__)

DEFAULT_TARGET_TEMP_C = 21.0
DEFAULT_FAN_SPEED_PCT = 50
DEFAULT_AC_POWER_ON = True
DEFAULT_GRPC_PORT = 50051
DEFAULT_INTERVAL_SECONDS = 5.0
DEFAULT_MULTICAST_GROUP = "239.255.0.1"
DEFAULT_MULTICAST_PORT = 9999
SOCKET_TIMEOUT_SEC = 0.5
DEFAULT_BASE_ROOM_TEMP_C = 23.0
RUNNING_POWER_WATTS = 1250.0
STANDBY_POWER_WATTS = 18.0
VOLTAGE_NOMINAL_VOLTS = 220.0
MAX_GRPC_WORKERS = 4
GRPC_SHUTDOWN_GRACE_SEC = 2.0


class UDPSocketProtocol(Protocol):
    """Protocol for sending UDP datagrams."""

    def sendto(self, data: bytes, target: tuple[str, int], /) -> int: ...
    def close(self) -> None: ...


def _now_ms() -> int:
    return int(time.time() * 1000)


class AirConditionerServicer(datamesh_pb2_grpc.AirConditionerServiceServicer):
    """gRPC servicer handling SetControl requests for Precision AC units."""

    def __init__(self, device: "AirConditionerDevice") -> None:
        self._device = device

    def SetControl(
        self,
        request: datamesh_pb2.ACControlRequest,
        context: grpc.ServicerContext | None,
    ) -> datamesh_pb2.ACControlResponse:
        """Applies target temperature, fan speed, and power state to the AC.

        Example:
            resp = servicer.SetControl(request, context)
        """
        logger.info(
            "Received SetControl for %s: power=%s target=%.1f°C fan=%d%%",
            request.device_id,
            request.power_on,
            request.target_temp_c,
            request.fan_speed_pct,
        )
        updated_info = self._device.apply_control(
            power_on=request.power_on,
            target_temp_c=request.target_temp_c,
            fan_speed_pct=request.fan_speed_pct,
        )
        return datamesh_pb2.ACControlResponse(
            success=True,
            message="AC setpoint updated successfully",
            updated_device=updated_info,
        )


class AirConditionerDevice:
    """Precision AC unit maintaining internal thermal state, streaming UDP telemetry,
    and serving remote actuation commands over gRPC.
    """

    def __init__(
        self,
        device_id: str = "ac-rack-01",
        grpc_port: int = DEFAULT_GRPC_PORT,
        advertised_ip: str = "",
        gateway_host: str | None = None,
        gateway_port: int | None = None,
        send_interval_sec: float = DEFAULT_INTERVAL_SECONDS,
        multicast_group: str = DEFAULT_MULTICAST_GROUP,
        multicast_port: int = DEFAULT_MULTICAST_PORT,
        socket_factory: Callable[[], UDPSocketProtocol] | None = None,
    ) -> None:
        self.device_id = device_id
        self.grpc_port = grpc_port
        self.advertised_ip = advertised_ip
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.send_interval_sec = send_interval_sec
        self.multicast_group = multicast_group
        self.multicast_port = multicast_port

        self.power_on: bool = DEFAULT_AC_POWER_ON
        self.target_temp_c: float = DEFAULT_TARGET_TEMP_C
        self.fan_speed_pct: int = DEFAULT_FAN_SPEED_PCT
        self.current_temp_c: float = DEFAULT_TARGET_TEMP_C + 0.8

        self._socket_factory: Callable[[], UDPSocketProtocol] = socket_factory or (
            lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        )
        self._sock: UDPSocketProtocol | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._stream_thread: threading.Thread | None = None
        self._mcast_thread: threading.Thread | None = None
        self._mcast_sock: socket.socket | None = None
        self._grpc_server: grpc.Server | None = None

    def apply_control(
        self,
        power_on: bool,
        target_temp_c: float,
        fan_speed_pct: int,
    ) -> datamesh_pb2.DeviceInfo:
        """Atomically applies actuation parameters and returns current DeviceInfo.

        Example:
            info = device.apply_control(True, 20.5, 75)
        """
        with self._lock:
            self.power_on = power_on
            if target_temp_c > 0.0:
                self.target_temp_c = target_temp_c
            if fan_speed_pct >= 0:
                self.fan_speed_pct = fan_speed_pct
            return self._build_device_info_locked()

    def to_device_info(self) -> datamesh_pb2.DeviceInfo:
        """Generates a DeviceInfo protobuf message snapshot of this AC device.

        Example:
            info = device.to_device_info()
        """
        with self._lock:
            return self._build_device_info_locked()

    def _build_device_info_locked(self) -> datamesh_pb2.DeviceInfo:
        state_str = "ON" if self.power_on else "OFF"
        summary = (
            f"AC {state_str} | Target: {self.target_temp_c:.1f}°C | "
            f"Fan: {self.fan_speed_pct}% | Temp: {self.current_temp_c:.1f}°C"
        )
        return datamesh_pb2.DeviceInfo(
            device_id=self.device_id,
            device_type=datamesh_pb2.AIR_CONDITIONER,
            ip=self.advertised_ip,
            grpc_port=self.grpc_port,
            is_online=True,
            state_summary=summary,
            last_seen_ms=_now_ms(),
        )

    def _simulate_thermal_dynamics(self) -> None:
        """Simulates physical room convergence towards target or ambient."""
        drift_rate = 0.2
        target = self.target_temp_c if self.power_on else DEFAULT_BASE_ROOM_TEMP_C
        noise = random.uniform(-0.05, 0.05)
        diff = target - self.current_temp_c
        self.current_temp_c += (diff * drift_rate) + noise

    def create_telemetry(self) -> datamesh_pb2.TelemetryPacket:
        """Simulates internal physics drift and produces a TelemetryPacket.

        Example:
            pkt = device.create_telemetry()
        """
        with self._lock:
            self._simulate_thermal_dynamics()
            pwr = (
                RUNNING_POWER_WATTS * (self.fan_speed_pct / 100.0)
                if self.power_on
                else STANDBY_POWER_WATTS
            )
            current = pwr / VOLTAGE_NOMINAL_VOLTS
            return datamesh_pb2.TelemetryPacket(
                device_id=self.device_id,
                device_type=datamesh_pb2.AIR_CONDITIONER,
                timestamp_ms=_now_ms(),
                is_alert=False,
                ac=datamesh_pb2.ACTelemetry(
                    temperature_c=round(self.current_temp_c, 2),
                    target_temp_c=round(self.target_temp_c, 2),
                    fan_speed_pct=self.fan_speed_pct,
                    power_watts=round(pwr, 2),
                    current_amps=round(current, 2),
                    voltage_volts=VOLTAGE_NOMINAL_VOLTS,
                    ac_power_on=self.power_on,
                ),
            )

    def send_telemetry(self) -> datamesh_pb2.TelemetryPacket | None:
        """Creates and transmits a single periodic telemetry packet over UDP unicast.

        Example:
            pkt = device.send_telemetry()
        """
        packet = self.create_telemetry()
        with self._lock:
            host, port = self.gateway_host, self.gateway_port
            if not host or not port:
                return None
            if not self._sock:
                self._sock = self._socket_factory()
            self._sock.sendto(packet.SerializeToString(), (host, port))
        return packet

    def send_initial_registration(self) -> None:
        """Sends an initial DeviceInfo registration datagram to the Gateway if known.

        Example:
            device.send_initial_registration()
        """
        with self._lock:
            host, port = self.gateway_host, self.gateway_port
            if not host or not port:
                return
            if not self._sock:
                self._sock = self._socket_factory()
            info = self._build_device_info_locked()
            self._sock.sendto(info.SerializeToString(), (host, port))

    def handle_discovery_request(self, raw_bytes: bytes) -> None:
        """Learns Gateway endpoint from discovery beacon and sends DeviceInfo response.

        Example:
            device.handle_discovery_request(raw_bytes)
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
            announcement = self._build_device_info_locked()
            self._sock.sendto(
                announcement.SerializeToString(),
                (self.gateway_host, self.gateway_port),
            )
        logger.info("Learned gateway at %s:%d via beacon", req.gateway_ip, req.telemetry_udp_port)

    def start_multicast_listener(self) -> None:
        """Binds and joins the multicast discovery group to listen for Gateway beacons.

        Example:
            device.start_multicast_listener()
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
                name="ac-mcast-listener",
            )
            self._mcast_thread.start()
            logger.info("Listening for beacons on %s:%d", self.multicast_group, self.multicast_port)
        except Exception as err:
            logger.warning("Could not bind multicast socket (%s). Using static endpoint.", err)

    def _multicast_listen_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._mcast_sock:
                break
            try:
                data, _ = self._mcast_sock.recvfrom(2048)
                self.handle_discovery_request(data)
            except TimeoutError:
                continue
            except Exception:
                break

    def start_grpc_server(self) -> grpc.Server:
        """Starts the gRPC server servicing SetControl requests.

        Example:
            server = device.start_grpc_server()
        """
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=MAX_GRPC_WORKERS))
        datamesh_pb2_grpc.add_AirConditionerServiceServicer_to_server(
            AirConditionerServicer(self), server
        )
        bind_address = f"0.0.0.0:{self.grpc_port}"
        bound_port = server.add_insecure_port(bind_address)
        if bound_port > 0:
            self.grpc_port = bound_port
        server.start()
        self._grpc_server = server
        logger.info("gRPC server for %s running on %s", self.device_id, bind_address)
        return server

    def start(self) -> None:
        """Starts periodic UDP telemetry background thread.

        Example:
            device.start()
        """
        self._stop_event.clear()
        self.send_initial_registration()
        self._stream_thread = threading.Thread(
            target=self._streaming_loop,
            daemon=True,
            name="ac-telemetry-stream",
        )
        self._stream_thread.start()

    def _streaming_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.send_telemetry()
            except Exception as err:
                logger.error("Error streaming AC telemetry: %s", err)
            self._stop_event.wait(self.send_interval_sec)

    def stop(self) -> None:
        """Stops all threads, shuts down gRPC server, and closes active sockets.

        Example:
            device.stop()
        """
        self._stop_event.set()
        if self._grpc_server:
            self._grpc_server.stop(grace=GRPC_SHUTDOWN_GRACE_SEC)
        if self._mcast_sock:
            try:
                self._mcast_sock.close()
            except Exception:
                pass
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
