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
LOG_FILE="/tmp/datamesh-demo.log"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

rm -f "${DB_PATH}" "${DB_PATH}-wal" "${DB_PATH}-shm" "${LOG_FILE}"

CORE_PIDS=()
declare -A SOURCE_PIDS=()
declare -A SOURCE_TYPES=()
declare -A SOURCE_PARAMS=()
SOURCE_ORDER=()
NEXT_TEMP_IDX=3
NEXT_PDU_IDX=3
CODENAME_IDX=0

ADJECTIVES=("frosty" "amber" "cobalt" "solar" "quantum" "crimson" "atomic" "sonic" "velvet" "hyper")
SCIENTISTS=("fermi" "lovelace" "maxwell" "hawking" "bohr" "planck" "gauss" "dirac" "noether" "euler")

generate_codename() {
    local adj="${ADJECTIVES[$((CODENAME_IDX % ${#ADJECTIVES[@]}))]}"
    local sci="${SCIENTISTS[$((CODENAME_IDX % ${#SCIENTISTS[@]}))]}"
    CODENAME_IDX=$((CODENAME_IDX + 1))
    echo "${adj}-${sci}"
}

# Limpa eventuais processos órfãos de execuções anteriores
pkill -f "python -m gateway.main" 2>/dev/null || true
pkill -f "python -m client.main" 2>/dev/null || true
pkill -f "python -m sources.ac.main" 2>/dev/null || true
pkill -f "python -m sources.temperature.main" 2>/dev/null || true
pkill -f "/tmp/datamesh-pdu" 2>/dev/null || true
fuser -k "${GATEWAY_TCP_PORT}/tcp" "${TELEMETRY_UDP_PORT}/udp" "${WEB_PORT}/tcp" 50051/tcp >/dev/null 2>&1 || true
sleep 0.3

cleanup() {
    echo ""
    echo "[DEMO] Encerrando processos do DataMesh DCIM..."
    for id in "${SOURCE_ORDER[@]:-}"; do
        pid="${SOURCE_PIDS[$id]:-}"
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    for pid in "${CORE_PIDS[@]:-}"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    rm -f "${DB_PATH}" "${DB_PATH}-wal" "${DB_PATH}-shm"
    echo "[DEMO] Todos os processos foram encerrados."
}
trap cleanup EXIT INT TERM

register_source() {
    local id="$1"
    local type="$2"
    local param="$3"
    local seen=0
    for existing in "${SOURCE_ORDER[@]:-}"; do
        if [[ "$existing" == "$id" ]]; then
            seen=1
            break
        fi
    done
    if [[ $seen -eq 0 ]]; then
        SOURCE_ORDER+=("$id")
    fi
    SOURCE_TYPES["$id"]="$type"
    SOURCE_PARAMS["$id"]="$param"
}

start_source() {
    local id="$1"
    local type="${SOURCE_TYPES[$id]}"
    local param="${SOURCE_PARAMS[$id]}"

    # Fontes sobem sem endereço do Gateway e só transmitem depois de receber o pedido de
    # descoberta multicast, que o Gateway repete a cada 5 s.
    if [[ "$type" == "temp" ]]; then
        SENSOR_ID="$id" BASE_TEMP_C="$param" GATEWAY_HOST="" \
            "$PYTHON_BIN" -m sources.temperature.main </dev/null >>"$LOG_FILE" 2>&1 &
        SOURCE_PIDS["$id"]=$!
    elif [[ "$type" == "pdu" ]]; then
        PDU_DEVICE_ID="$id" BASE_POWER_WATTS="$param" GATEWAY_HOST="" \
            /tmp/datamesh-pdu >>"$LOG_FILE" 2>&1 &
        SOURCE_PIDS["$id"]=$!
    elif [[ "$type" == "ac" ]]; then
        AC_DEVICE_ID="$id" AC_GRPC_PORT="$param" GATEWAY_HOST="" \
            "$PYTHON_BIN" -m sources.ac.main >>"$LOG_FILE" 2>&1 &
        SOURCE_PIDS["$id"]=$!
    fi
}

is_running() {
    local id="$1"
    local pid="${SOURCE_PIDS[$id]:-}"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

echo "[DEMO] Compilando binário Go da PDU..."
go build -o /tmp/datamesh-pdu ./sources/pdu/cmd/main.go

echo "[DEMO] Iniciando Gateway Central (TCP :${GATEWAY_TCP_PORT}, UDP :${TELEMETRY_UDP_PORT}, Multicast ${MULTICAST_GROUP}:${MULTICAST_PORT})..."
"$PYTHON_BIN" -m gateway.main >>"$LOG_FILE" 2>&1 &
CORE_PIDS+=($!)
sleep 1

echo "[DEMO] Iniciando Cliente Web FastAPI em http://localhost:${WEB_PORT} ..."
GATEWAY_PORT="${GATEWAY_TCP_PORT}" "$PYTHON_BIN" -m client.main >>"$LOG_FILE" 2>&1 &
CORE_PIDS+=($!)

# Registra e inicia topologia inicial multi-rack com codinomes estilo Docker
register_source "ac-01-carnot" "ac" "50051"
register_source "temp-01-turing" "temp" "22.5"
register_source "temp-02-curie" "temp" "26.0"
register_source "pdu-01-tesla" "pdu" "1400"
register_source "pdu-02-faraday" "pdu" "1850"

for id in "${SOURCE_ORDER[@]}"; do
    start_source "$id"
done
sleep 0.5

if [[ "${1:-}" == "--smoke" ]]; then
    echo "[DEMO] Aguardando a descoberta das 5 fontes..."
    found=0
    for _ in {1..30}; do
        devs="$(curl -fsS "http://127.0.0.1:${WEB_PORT}/api/devices" 2>/dev/null || true)"
        if echo "$devs" | grep -q "pdu-01-tesla" && \
           echo "$devs" | grep -q "pdu-02-faraday" && \
           echo "$devs" | grep -q "temp-01-turing" && \
           echo "$devs" | grep -q "temp-02-curie" && \
           echo "$devs" | grep -q "ac-01-carnot"; then
            found=1
            break
        fi
        sleep 0.5
    done
    if [[ $found -eq 0 ]]; then
        echo "[DEMO] Falha: nem todas as fontes foram descobertas em 15 s."
        exit 1
    fi
    # As fontes só começam a transmitir depois da descoberta. Espera um ciclo de envio
    # para as consultas já encontrarem leituras.
    sleep "$(awk "BEGIN { print ${SEND_INTERVAL_SEC} + 1 }")"

    echo "[DEMO] Disparando anomalia (acima de 35 °C) via SIGUSR1 em temp-02-curie..."
    kill -USR1 "${SOURCE_PIDS["temp-02-curie"]}"
    sleep 0.5

    echo "[DEMO] Verificando /api/devices (5 fontes ativas):"
    curl -fsS "http://127.0.0.1:${WEB_PORT}/api/devices"
    echo ""

    echo "[DEMO] Verificando /api/ac/control (atuação gRPC):"
    curl -fsS -X POST "http://127.0.0.1:${WEB_PORT}/api/ac/control" \
        -H "Content-Type: application/json" \
        -d '{"device_id":"ac-01-carnot","power_on":true,"target_temp_c":19.5,"fan_speed_pct":85}'
    echo ""

    echo "[DEMO] Verificando as 3 Consultas Analíticas Agregadas:"
    curl -fsS "http://127.0.0.1:${WEB_PORT}/api/analytics/hottest_rack?window_seconds=300" && echo ""
    curl -fsS "http://127.0.0.1:${WEB_PORT}/api/analytics/avg_pdu_power?window_seconds=300" && echo ""
    curl -fsS "http://127.0.0.1:${WEB_PORT}/api/analytics/thermal_stability?window_seconds=300" && echo ""
    echo "[DEMO] Smoke test concluído com sucesso!"
    exit 0
fi

print_status_table() {
    echo ""
    echo "----------------------------------------------------------------------------"
    printf " %-22s | %-8s | %-14s | %-18s\n" "DEVICE ID" "TIPO" "PARÂMETRO" "ESTADO DO PROCESSO"
    echo "----------------------------------------------------------------------------"
    for id in "${SOURCE_ORDER[@]}"; do
        local t="${SOURCE_TYPES[$id]}"
        local p="${SOURCE_PARAMS[$id]}"
        local p_desc=""
        [[ "$t" == "temp" ]] && p_desc="Base ${p}°C"
        [[ "$t" == "pdu" ]]  && p_desc="Base ${p}W"
        [[ "$t" == "ac" ]]   && p_desc="gRPC :${p}"
        if is_running "$id"; then
            printf " %-22s | %-8s | %-14s | \033[32mATIVO (PID %s)\033[0m\n" "$id" "$t" "$p_desc" "${SOURCE_PIDS[$id]}"
        else
            printf " %-22s | %-8s | %-14s | \033[31mPARADO (FALHA)\033[0m\n" "$id" "$t" "$p_desc"
        fi
    done
    echo "----------------------------------------------------------------------------"
}

trigger_anomaly_menu() {
    echo ""
    echo "Sensores de temperatura ativos:"
    local active_temps=()
    local idx=1
    for id in "${SOURCE_ORDER[@]}"; do
        if [[ "${SOURCE_TYPES[$id]}" == "temp" ]] && is_running "$id"; then
            echo "  [$idx] $id (Base ${SOURCE_PARAMS[$id]}°C)"
            active_temps+=("$id")
            idx=$((idx + 1))
        fi
    done
    if [[ ${#active_temps[@]} -eq 0 ]]; then
        echo "  Nenhum sensor de temperatura ativo no momento."
        return
    fi
    read -r -p "Escolha o número do sensor [padrão: 1 (${active_temps[0]})]: " choice
    choice="${choice:-1}"
    local sel_idx=$((choice - 1))
    if [[ $sel_idx -ge 0 && $sel_idx -lt ${#active_temps[@]} ]]; then
        local target_id="${active_temps[$sel_idx]}"
        kill -USR1 "${SOURCE_PIDS[$target_id]}"
        echo "  ${target_id} enviou alerta imediato de anomalia (38.8 °C, limiar 35 °C)."
    else
        echo "  Opção inválida."
    fi
}

add_sensor_menu() {
    echo ""
    echo "Qual tipo de fonte deseja adicionar dinamicamente?"
    echo "  [1] Sensor de Temperatura de Rack (Python)"
    echo "  [2] PDU de Rack (Go)"
    read -r -p "Escolha [padrão: 1]: " stype
    stype="${stype:-1}"

    local adj="${ADJECTIVES[$((CODENAME_IDX % ${#ADJECTIVES[@]}))]}"
    local sci="${SCIENTISTS[$((CODENAME_IDX % ${#SCIENTISTS[@]}))]}"
    local codename="${adj}-${sci}"
    CODENAME_IDX=$((CODENAME_IDX + 1))

    if [[ "$stype" == "2" ]]; then
        local rack_num
        rack_num=$(printf "%02d" "$NEXT_PDU_IDX")
        local new_id="pdu-${rack_num}-${codename}"
        local base_w=$((1200 + (NEXT_PDU_IDX * 250)))
        NEXT_PDU_IDX=$((NEXT_PDU_IDX + 1))
        register_source "$new_id" "pdu" "$base_w"
        start_source "$new_id"
        echo "  PDU ${new_id} (${base_w} W) iniciada (PID ${SOURCE_PIDS[$new_id]}). Aparece no Dashboard após o próximo pedido de descoberta (até 5 s)."
    else
        local rack_num
        rack_num=$(printf "%02d" "$NEXT_TEMP_IDX")
        local new_id="temp-${rack_num}-${codename}"
        local base_t="24.5"
        NEXT_TEMP_IDX=$((NEXT_TEMP_IDX + 1))
        register_source "$new_id" "temp" "$base_t"
        start_source "$new_id"
        sleep 0.4
        echo "  Sensor ${new_id} (${base_t} °C) iniciado (PID ${SOURCE_PIDS[$new_id]}). Aparece no Dashboard após o próximo pedido de descoberta (até 5 s)."
    fi
}

stop_source_menu() {
    echo ""
    echo "Fontes em execução (escolha uma para simular queda/falha):"
    local running_ids=()
    local idx=1
    for id in "${SOURCE_ORDER[@]}"; do
        if is_running "$id"; then
            echo "  [$idx] $id (${SOURCE_TYPES[$id]})"
            running_ids+=("$id")
            idx=$((idx + 1))
        fi
    done
    if [[ ${#running_ids[@]} -eq 0 ]]; then
        echo "  Nenhuma fonte em execução."
        return
    fi
    read -r -p "Escolha o número da fonte para derrubar [padrão: 1 (${running_ids[0]})]: " choice
    choice="${choice:-1}"
    local sel_idx=$((choice - 1))
    if [[ $sel_idx -ge 0 && $sel_idx -lt ${#running_ids[@]} ]]; then
        local target_id="${running_ids[$sel_idx]}"
        kill -TERM "${SOURCE_PIDS[$target_id]}" 2>/dev/null || true
        wait "${SOURCE_PIDS[$target_id]}" 2>/dev/null || true
        echo "  Fonte ${target_id} desligada. Depois de 15 s sem telemetria o Gateway a marca como OFFLINE."
    else
        echo "  Opção inválida."
    fi
}

restart_source_menu() {
    echo ""
    echo "Fontes paradas (em falha):"
    local stopped_ids=()
    local idx=1
    for id in "${SOURCE_ORDER[@]}"; do
        if ! is_running "$id"; then
            echo "  [$idx] $id (${SOURCE_TYPES[$id]})"
            stopped_ids+=("$id")
            idx=$((idx + 1))
        fi
    done
    if [[ ${#stopped_ids[@]} -eq 0 ]]; then
        echo "  Todas as fontes já estão ativas."
        return
    fi
    read -r -p "Escolha o número da fonte para religar [padrão: 1 (${stopped_ids[0]})]: " choice
    choice="${choice:-1}"
    local sel_idx=$((choice - 1))
    if [[ $sel_idx -ge 0 && $sel_idx -lt ${#stopped_ids[@]} ]]; then
        local target_id="${stopped_ids[$sel_idx]}"
        start_source "$target_id"
        echo "  Fonte ${target_id} religada (PID ${SOURCE_PIDS[$target_id]}). Volta a ONLINE após o próximo pedido de descoberta."
    else
        echo "  Opção inválida."
    fi
}

while true; do
    echo ""
    echo "======================================================================"
    echo "  DataMesh DCIM, console de demonstração"
    echo "  Dashboard: http://localhost:${WEB_PORT}"
    echo "  Logs: tail -f ${LOG_FILE}"
    echo "======================================================================"
    echo "  [1] Disparar anomalia térmica (acima de 35 °C) em um sensor"
    echo "  [2] Adicionar sensor ou PDU com a demo rodando"
    echo "  [3] Simular falha de uma fonte (ONLINE para OFFLINE)"
    echo "  [4] Religar uma fonte parada (OFFLINE para ONLINE)"
    echo "  [5] Listar o estado dos processos"
    echo "  [6] Mostrar as últimas 15 linhas do log"
    echo "  [q] Encerrar a demonstração"
    echo "======================================================================"
    read -r -p "Selecione uma ação: " action || break
    case "$action" in
        1) trigger_anomaly_menu ;;
        2) add_sensor_menu ;;
        3) stop_source_menu ;;
        4) restart_source_menu ;;
        5) print_status_table ;;
        6) echo ""; tail -n 15 "$LOG_FILE" || true ;;
        q|Q) break ;;
        *) echo "  Opção inválida. Use 1 a 6 ou q." ;;
    esac
done
