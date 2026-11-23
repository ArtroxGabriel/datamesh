#!/bin/sh
set -eu
ip route add 224.0.0.0/4 dev eth0 2>/dev/null || true
exec "$@"
