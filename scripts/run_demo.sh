#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PYTHONPATH="${ROOT_DIR}:${ROOT_DIR}/gen/python"
export GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"
export GATEWAY_TCP_PORT="${GATEWAY_TCP_PORT:-9997}"
export GATEWAY_PORT="${GATEWAY_PORT:-9997}"
export TELEMETRY_UDP_PORT="${TELEMETRY_UDP_PORT:-9998}"
export MULTICAST_GROUP="${MULTICAST_GROUP:-239.255.0.1}"
export MULTICAST_PORT="${MULTICAST_PORT:-9999}"
export WEB_PORT="${WEB_PORT:-8080}"
export SEND_INTERVAL_SEC="${SEND_INTERVAL_SEC:-2.0}"
export DB_PATH="${DB_PATH:-/tmp/datamesh-demo.db}"

PIDS=()

cleanup() {
    echo ""
    echo "[DEMO] Stopping DataMesh DCIM processes..."
    for pid in "${PIDS[@]:-}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    echo "[DEMO] All processes stopped."
}
trap cleanup EXIT INT TERM

echo "[DEMO] Building Go PDU binary..."
go build -o /tmp/datamesh-pdu ./sources/pdu/cmd/main.go

echo "[DEMO] 1/5 Starting Gateway (TCP :${GATEWAY_TCP_PORT}, UDP :${TELEMETRY_UDP_PORT}, Multicast ${MULTICAST_GROUP}:${MULTICAST_PORT})..."
uv run python -m gateway.main &
PIDS+=($!)
sleep 1

echo "[DEMO] 2/5 Starting Precision Air Conditioner (gRPC :50051)..."
GATEWAY_PORT="${TELEMETRY_UDP_PORT}" uv run python -m sources.ac.main &
PIDS+=($!)

echo "[DEMO] 3/5 Starting Rack PDU (Go)..."
GATEWAY_PORT="${TELEMETRY_UDP_PORT}" /tmp/datamesh-pdu &
PIDS+=($!)

echo "[DEMO] 4/5 Starting FastAPI Web Client on http://localhost:${WEB_PORT} ..."
GATEWAY_PORT="${GATEWAY_TCP_PORT}" uv run python -m client.main &
PIDS+=($!)

if [[ "${1:-}" == "--smoke" ]]; then
    echo "[DEMO] 5/5 Starting Rack Temperature Sensor (smoke mode)..."
    GATEWAY_PORT="${TELEMETRY_UDP_PORT}" uv run python -m sources.temperature.main </dev/null &
    PIDS+=($!)

    echo "[DEMO] Waiting for telemetry ingestion from all 3 heterogeneous sources..."
    for _ in {1..30}; do
        if curl -fsS "http://127.0.0.1:${WEB_PORT}/api/devices" 2>/dev/null | grep -q "pdu-rack-01" && \
           curl -fsS "http://127.0.0.1:${WEB_PORT}/api/devices" 2>/dev/null | grep -q "ac-rack-01" && \
           curl -fsS "http://127.0.0.1:${WEB_PORT}/api/devices" 2>/dev/null | grep -q "temp-rack-01"; then
            break
        fi
        sleep 0.5
    done

    echo "[DEMO] Verifying /api/devices:"
    curl -fsS "http://127.0.0.1:${WEB_PORT}/api/devices"
    echo ""

    echo "[DEMO] Verifying /api/ac/control (gRPC actuation):"
    curl -fsS -X POST "http://127.0.0.1:${WEB_PORT}/api/ac/control" \
        -H "Content-Type: application/json" \
        -d '{"device_id":"ac-rack-01","power_on":true,"target_temp_c":19.5,"fan_speed_pct":85}'
    echo ""

    echo "[DEMO] Verifying 3 Analytical Queries:"
    curl -fsS "http://127.0.0.1:${WEB_PORT}/api/analytics/hottest_rack?window_seconds=300" && echo ""
    curl -fsS "http://127.0.0.1:${WEB_PORT}/api/analytics/avg_pdu_power?window_seconds=300" && echo ""
    curl -fsS "http://127.0.0.1:${WEB_PORT}/api/analytics/thermal_stability?window_seconds=300" && echo ""
    echo "[DEMO] Smoke test succeeded!"
    exit 0
fi

echo "[DEMO] 5/5 Starting Rack Temperature Sensor in foreground (press [ENTER] to trigger >35°C alert, Ctrl+C to stop all)..."
GATEWAY_PORT="${TELEMETRY_UDP_PORT}" uv run python -m sources.temperature.main
