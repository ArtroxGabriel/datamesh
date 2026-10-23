"""gRPC Proxy adapter for precision air conditioner control."""

from typing import Protocol

import datamesh_pb2
import datamesh_pb2_grpc
import grpc


class ACControlProxy(Protocol):
    """Protocol for sending control commands to precision air conditioners."""

    def send_ac_control(
        self, device: datamesh_pb2.DeviceInfo, command: datamesh_pb2.ACControlRequest
    ) -> datamesh_pb2.ACControlResponse:
        """Sends an actuation command to the specified AC device."""
        ...


class GrpcACControlProxy:
    """Production gRPC client communicating with remote AC actuator sources."""

    def __init__(self, timeout_seconds: float = 3.0) -> None:
        self._timeout = timeout_seconds

    def send_ac_control(
        self, device: datamesh_pb2.DeviceInfo, command: datamesh_pb2.ACControlRequest
    ) -> datamesh_pb2.ACControlResponse:
        """Invokes SetControl RPC on target AC unit over gRPC.

        Example:
            resp = proxy.send_ac_control(ac_device, control_cmd)
        """
        target = f"{device.ip}:{device.grpc_port}"
        try:
            with grpc.insecure_channel(target) as channel:
                stub = datamesh_pb2_grpc.AirConditionerServiceStub(channel)
                return stub.SetControl(command, timeout=self._timeout)
        except grpc.RpcError as rpc_err:
            return datamesh_pb2.ACControlResponse(
                success=False,
                message=f"gRPC error connecting to {target}: {rpc_err}",
            )
        except Exception as err:
            return datamesh_pb2.ACControlResponse(
                success=False,
                message=f"Failed to control AC at {target}: {err}",
            )
