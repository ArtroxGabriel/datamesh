"""Core Gateway service coordinating UDP telemetry, discovery, and TCP client sessions."""

import logging
import socket
import threading

import datamesh_pb2

from common.framing import recv_proto, send_proto
from gateway.proxy import ACControlProxy, GrpcACControlProxy
from gateway.registry import DeviceRegistry
from gateway.storage import GatewayStorageProtocol, TelemetryStorage

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_LIMIT = 50
DEFAULT_ANALYTICS_WINDOW_SEC = 300
TCP_LISTEN_BACKLOG = 10
TCP_SOCKET_TIMEOUT_SEC = 0.5


class GatewayCoordinator:
    """Orchestrates DCIM telemetry ingestion, storage, discovery, and TCP client requests."""

    def __init__(
        self,
        storage: GatewayStorageProtocol | None = None,
        registry: DeviceRegistry | None = None,
        ac_proxy: ACControlProxy | None = None,
    ) -> None:
        self.storage: GatewayStorageProtocol = storage or TelemetryStorage()
        self.registry: DeviceRegistry = registry or DeviceRegistry()
        self.ac_proxy: ACControlProxy = ac_proxy or GrpcACControlProxy()
        self._tcp_server_sock: socket.socket | None = None
        self._tcp_thread: threading.Thread | None = None
        self._running = False

    def handle_client_request(
        self,
        request: datamesh_pb2.ClientRequest,
        current_time_ms: int | None = None,
    ) -> datamesh_pb2.ClientResponse:
        """Processes an incoming TCP client request and produces a response.

        Example:
            resp = coordinator.handle_client_request(request)
        """
        if request.action == datamesh_pb2.LIST_DEVICES:
            devices = self.registry.list_devices(current_time_ms)
            return datamesh_pb2.ClientResponse(success=True, devices=devices)

        if request.action == datamesh_pb2.GET_HISTORY:
            limit = request.history_limit if request.history_limit > 0 else DEFAULT_HISTORY_LIMIT
            history = self.storage.get_recent_history(limit)
            return datamesh_pb2.ClientResponse(success=True, history=history)

        if request.action == datamesh_pb2.QUERY_ANALYTICS:
            return self._handle_analytics(request.query_type, request.window_seconds)

        if request.action == datamesh_pb2.CONTROL_AC:
            return self._handle_control_ac(request.ac_control)

        return datamesh_pb2.ClientResponse(
            success=False, message=f"Unknown client action: {request.action}"
        )

    def _handle_analytics(
        self, query_type: int, window_seconds: int
    ) -> datamesh_pb2.ClientResponse:
        window = window_seconds if window_seconds > 0 else DEFAULT_ANALYTICS_WINDOW_SEC
        if query_type == datamesh_pb2.HOTTEST_RACK:
            result = self.storage.query_hottest_rack(window)
        elif query_type == datamesh_pb2.AVG_PDU_POWER:
            result = self.storage.query_average_pdu_power(window)
        elif query_type == datamesh_pb2.THERMAL_STABILITY:
            result = self.storage.query_thermal_stability(window)
        else:
            return datamesh_pb2.ClientResponse(
                success=False, message=f"Unsupported query type: {query_type}"
            )
        return datamesh_pb2.ClientResponse(success=True, analytics=result)

    def _handle_control_ac(
        self, command: datamesh_pb2.ACControlRequest
    ) -> datamesh_pb2.ClientResponse:
        device = self.registry.get_device(command.device_id)
        if device is None or device.device_type != datamesh_pb2.AIR_CONDITIONER:
            return datamesh_pb2.ClientResponse(
                success=False,
                message=f"AC device '{command.device_id}' not found or invalid type",
            )

        resp = self.ac_proxy.send_ac_control(device, command)
        if resp.success and resp.HasField("updated_device"):
            self.registry.register_device(resp.updated_device)
        message = resp.message or ("Success" if resp.success else "AC command failed")
        return datamesh_pb2.ClientResponse(success=resp.success, message=message)

    def handle_udp_datagram(self, raw_bytes: bytes, sender_addr: tuple[str, int]) -> None:
        """Parses and handles a raw UDP datagram (DeviceInfo or TelemetryPacket).

        Example:
            coordinator.handle_udp_datagram(data, addr)
        """
        # Try decoding as TelemetryPacket first (high frequency continuous stream)
        telemetry = datamesh_pb2.TelemetryPacket()
        try:
            telemetry.ParseFromString(raw_bytes)
            if (
                telemetry.device_id
                and telemetry.timestamp_ms > 0
                and telemetry.device_type != datamesh_pb2.DEVICE_TYPE_UNKNOWN
            ):
                self.storage.record_telemetry(telemetry)
                self.registry.update_from_telemetry(telemetry)
                return
        except Exception:
            pass

        # Try decoding as DeviceInfo (discovery announcement)
        device = datamesh_pb2.DeviceInfo()
        try:
            device.ParseFromString(raw_bytes)
            if device.device_id:
                if not device.ip:
                    device.ip = sender_addr[0]
                self.registry.register_device(device)
        except Exception as err:
            logger.warning("Unrecognized UDP datagram from %s: %s", sender_addr, err)

    def send_discovery_beacon(
        self,
        multicast_group: str = "239.255.0.1",
        multicast_port: int = 9999,
        gateway_ip: str = "127.0.0.1",
        udp_port: int = 9998,
    ) -> None:
        """Broadcasts a DiscoveryRequest over UDP multicast to trigger source announcements.

        Example:
            coordinator.send_discovery_beacon()
        """
        beacon = datamesh_pb2.DiscoveryRequest(gateway_ip=gateway_ip, telemetry_udp_port=udp_port)
        data = beacon.SerializeToString()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.sendto(data, (multicast_group, multicast_port))

    def start_tcp_server(self, host: str = "0.0.0.0", port: int = 9997) -> int:
        """Starts TCP client listener thread on host:port, returning the bound port.

        Example:
            port = coordinator.start_tcp_server("127.0.0.1", 9997)
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(TCP_LISTEN_BACKLOG)
        sock.settimeout(TCP_SOCKET_TIMEOUT_SEC)

        self._tcp_server_sock = sock
        self._running = True
        bound_port = sock.getsockname()[1]

        self._tcp_thread = threading.Thread(
            target=self._tcp_accept_loop, daemon=True, name="gateway-tcp-listener"
        )
        self._tcp_thread.start()
        return bound_port

    def _tcp_accept_loop(self) -> None:
        while self._running and self._tcp_server_sock:
            try:
                conn, _ = self._tcp_server_sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            client_t = threading.Thread(
                target=self._handle_client_connection,
                args=(conn,),
                daemon=True,
            )
            client_t.start()

    def _handle_client_connection(self, conn: socket.socket) -> None:
        with conn:
            while self._running:
                try:
                    request = recv_proto(conn, datamesh_pb2.ClientRequest)
                    try:
                        response = self.handle_client_request(request)
                    except Exception as err:
                        logger.exception("Error processing client request: %s", err)
                        response = datamesh_pb2.ClientResponse(
                            success=False,
                            message=f"Internal server error: {err}",
                        )
                    send_proto(conn, response)
                except (ConnectionError, EOFError, ValueError):
                    break

    def stop_tcp_server(self) -> None:
        """Stops the TCP client server thread and closes listener socket.

        Example:
            coordinator.stop_tcp_server()
        """
        self._running = False
        if self._tcp_server_sock:
            try:
                self._tcp_server_sock.close()
            except Exception:
                pass
            self._tcp_server_sock = None
        if self._tcp_thread and self._tcp_thread.is_alive():
            self._tcp_thread.join(timeout=1.0)

    def close(self) -> None:
        """Closes all background resources and storage connections.

        Example:
            coordinator.close()
        """
        self.stop_tcp_server()
        self.storage.close()
