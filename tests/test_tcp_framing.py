import socket
import struct

import datamesh_pb2
import pytest

from common.framing import MAX_FRAME_BYTES, recv_proto, send_proto


class FragmentedSocket:
    """Fake socket that returns at most `chunk_size` bytes per recv() call."""

    def __init__(self, buffer: bytes, chunk_size: int = 2) -> None:
        self._buffer = buffer
        self._offset = 0
        self._chunk_size = chunk_size

    def recv(self, bufsize: int, /) -> bytes:
        if self._offset >= len(self._buffer):
            return b""
        step = min(bufsize, self._chunk_size)
        chunk = self._buffer[self._offset : self._offset + step]
        self._offset += len(chunk)
        return chunk


def test_send_and_receive_complete_protobuf_message() -> None:
    # Arrange
    left, right = socket.socketpair()
    original = datamesh_pb2.ClientRequest(
        action=datamesh_pb2.LIST_DEVICES,
        window_seconds=600,
    )

    try:
        # Act
        send_proto(left, original)
        received = recv_proto(right, datamesh_pb2.ClientRequest)

        # Assert
        assert received.action == datamesh_pb2.LIST_DEVICES
        assert received.window_seconds == 600
    finally:
        left.close()
        right.close()


def test_receive_handles_fragmented_tcp_stream() -> None:
    # Arrange
    payload = datamesh_pb2.ClientResponse(
        success=True,
        message="Fragmented stream test payload",
    ).SerializeToString()
    raw_frame = struct.pack(">I", len(payload)) + payload
    frag_sock = FragmentedSocket(raw_frame, chunk_size=2)

    # Act
    received = recv_proto(frag_sock, datamesh_pb2.ClientResponse)

    # Assert
    assert received.success is True
    assert received.message == "Fragmented stream test payload"


def test_receive_raises_connection_closed_on_eof() -> None:
    # Arrange
    frag_sock = FragmentedSocket(b"\x00\x00", chunk_size=2)

    # Act & Assert
    with pytest.raises(ConnectionError, match="Connection closed"):
        recv_proto(frag_sock, datamesh_pb2.ClientRequest)


def test_rejects_invalid_or_oversized_frame_length() -> None:
    # Arrange
    zero_header = FragmentedSocket(struct.pack(">I", 0))
    huge_header = FragmentedSocket(struct.pack(">I", MAX_FRAME_BYTES + 1))
    left, right = socket.socketpair()

    try:
        # Act & Assert
        with pytest.raises(ValueError, match="Invalid frame length"):
            send_proto(left, datamesh_pb2.ClientRequest())

        with pytest.raises(ValueError, match="Invalid frame length"):
            recv_proto(zero_header, datamesh_pb2.ClientRequest)

        with pytest.raises(ValueError, match="Invalid frame length"):
            recv_proto(huge_header, datamesh_pb2.ClientRequest)
    finally:
        left.close()
        right.close()
