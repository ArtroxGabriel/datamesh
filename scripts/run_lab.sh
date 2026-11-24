#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

compose() {
    docker compose -p datamesh-security-lab -f compose.lab.yml --profile attack "$@"
}

start_mode() {
    local mode="$1"
    scripts/security/setup_lab.sh
    echo "[LAB] Subindo pilha em modo ${mode}..."
    DATAMESH_SECURITY_MODE="$mode" compose up -d --build --force-recreate
}

run_attack_menu() {
    echo ""
    echo "Ataques disponíveis:"
    echo "  [1] sniff  — capturar telemetria UDP"
    echo "  [2] hijack — tentar controlar AC via gRPC"
    echo "  [3] replay — capturar pacote e reenviar após anomalia"
    read -r -p "Escolha [1-3]: " atk
    case "$atk" in
        1) compose exec attacker python scripts/attacks/lab_attack.py sniff --lab compose ;;
        2) compose exec attacker python scripts/attacks/lab_attack.py hijack --lab compose ;;
        3) compose exec attacker python scripts/attacks/lab_attack.py replay --lab compose ;;
        *) echo "  Opção inválida." ;;
    esac
}

while true; do
    echo ""
    echo "======================================================================"
    echo "  DataMesh DCIM · Menu do Laboratório Docker"
    echo "  Console Lab: http://127.0.0.1:8081  |  Dashboard: http://localhost:8080"
    echo "======================================================================"
    echo "  [1] Subir / trocar para modo INSEGURO"
    echo "  [2] Subir / trocar para modo SEGURO"
    echo "  [3] Disparar anomalia térmica (temperature)"
    echo "  [4] Disparar sobrecarga elétrica (pdu)"
    echo "  [5] Executar ataque via CLI (sniff / hijack / replay)"
    echo "  [6] Status dos containers"
    echo "  [7] Últimas 30 linhas de log do Gateway"
    echo "  [8] Derrubar laboratório (down)"
    echo "  [q] Sair do menu"
    echo "======================================================================"
    read -r -p "Selecione uma ação: " action || break
    case "$action" in
        1) start_mode insecure ;;
        2) start_mode secure ;;
        3) compose kill -s USR1 temperature && echo "[LAB] Anomalia térmica disparada." ;;
        4) compose kill -s USR1 pdu && echo "[LAB] Sobrecarga elétrica disparada." ;;
        5) run_attack_menu ;;
        6) compose ps ;;
        7) compose logs --tail=30 gateway ;;
        8) compose down ;;
        q|Q) break ;;
        *) echo "  Opção inválida. Use 1 a 8 ou q." ;;
    esac
done
