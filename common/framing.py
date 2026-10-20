"""Length-prefixed Protocol Buffers framing over TCP streams."""

import struct
from typing import Protocol

from google.protobuf.message import Message

HEADER_FORMAT = ">I"
HEADER_BYTES = 4
MAX_FRAME_BYTES = 4 * 1024 * 1024


class StreamReader(Protocol):
    def recv(self, bufsize: int, /) -> bytes: ...


class StreamWriter(Protocol):
    def sendall(self, data: bytes, /) -> None: ...


def recv_exact(reader: StreamReader, num_bytes: int) -> bytes:
    """Read exactly `num_bytes` from a TCP stream, handling packet fragmentation.

    Example:
        raw_header = recv_exact(sock, 4)
    """
    chunks: list[bytes] = []
    remaining = num_bytes
    while remaining > 0:
        chunk = reader.recv(remaining)
        if not chunk:
            read_so_far = num_bytes - remaining
            raise ConnectionError(
                f"Connection closed after {read_so_far} bytes; expected {num_bytes} bytes"
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_proto(writer: StreamWriter, message: Message) -> None:
    """Serialize and send a Protobuf message prefixed by a 4-byte big-endian length.

    Example:
        send_proto(client_sock, ClientRequest(action=LIST_DEVICES))
    """
    payload = message.SerializeToString()
    payload_len = len(payload)
    if payload_len == 0 or payload_len > MAX_FRAME_BYTES:
        raise ValueError(f"Invalid frame length {payload_len}; expected 1..{MAX_FRAME_BYTES} bytes")
    header = struct.pack(HEADER_FORMAT, payload_len)
    writer.sendall(header + payload)


def recv_proto[ProtoMsgT: Message](reader: StreamReader, message_cls: type[ProtoMsgT]) -> ProtoMsgT:
    """Read a length-prefixed frame from a TCP stream and parse into `message_cls`.

    Example:
        request = recv_proto(conn, ClientRequest)
    """
    header_bytes = recv_exact(reader, HEADER_BYTES)
    (frame_length,) = struct.unpack(HEADER_FORMAT, header_bytes)
    if frame_length <= 0 or frame_length > MAX_FRAME_BYTES:
        raise ValueError(
            f"Invalid frame length {frame_length}; expected 1..{MAX_FRAME_BYTES} bytes"
        )
    payload = recv_exact(reader, frame_length)
    message = message_cls()
    message.ParseFromString(payload)
    return message
