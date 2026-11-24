"""TLS credentials for the DataMesh demonstration lab."""

import os
import ssl
from pathlib import Path

import grpc


def secure_mode() -> bool:
    mode = os.environ.get("DATAMESH_SECURITY_MODE", "insecure")
    if mode not in {"insecure", "secure"}:
        raise ValueError("DATAMESH_SECURITY_MODE must be insecure or secure")
    return mode == "secure"


def credential_path(name: str) -> Path:
    return Path(os.environ.get("DATAMESH_CREDENTIALS_DIR", ".datamesh-security")) / name


def server_context() -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(credential_path("gateway.crt"), credential_path("gateway.key"))
    context.load_verify_locations(cafile=credential_path("ca.crt"))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def client_context() -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=credential_path("ca.crt"))
    context.load_cert_chain(credential_path("client.crt"), credential_path("client.key"))
    return context


def grpc_server_credentials() -> grpc.ServerCredentials:
    return grpc.ssl_server_credentials(
        [(credential_path("ac.key").read_bytes(), credential_path("ac.crt").read_bytes())],
        root_certificates=credential_path("ca.crt").read_bytes(),
        require_client_auth=True,
    )


def grpc_gateway_credentials() -> grpc.ChannelCredentials:
    return grpc.ssl_channel_credentials(
        root_certificates=credential_path("ca.crt").read_bytes(),
        private_key=credential_path("gateway.key").read_bytes(),
        certificate_chain=credential_path("gateway.crt").read_bytes(),
    )


def peer_common_name(cert: dict) -> str | None:
    for group in cert.get("subject", ()):
        for name, value in group:
            if name == "commonName":
                return value
    return None
