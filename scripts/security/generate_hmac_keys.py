#!/usr/bin/env python3
"""Provision HMAC keys for the gateway and explicitly named demo devices."""

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("device_ids", nargs="+", help="identities to provision")
    args = parser.parse_args()
    directory = Path(os.getenv("DATAMESH_CREDENTIALS_DIR", ".datamesh-security")) / "hmac"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for identity in ["gateway", *args.device_ids]:
        if not identity or Path(identity).name != identity or identity in {".", ".."}:
            parser.error(f"invalid device identity: {identity}")
        path = directory / f"{identity}.key"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            print(f"Keeping existing key: {path}")
            continue
        with os.fdopen(fd, "wb") as handle:
            handle.write(os.urandom(32))
        print(f"Created key: {path}")


if __name__ == "__main__":
    main()
