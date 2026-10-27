#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "=========================================================="
echo " [CLEANUP] Iniciando limpeza completa do DataMesh DCIM"
echo "=========================================================="

# 1. Encerra processos remanescentes e libera portas
echo "[1/5] Encerrando processos e liberando portas do sistema..."
pkill -f "python -m gateway.main" 2>/dev/null || true
pkill -f "python -m client.main" 2>/dev/null || true
pkill -f "python -m sources.ac.main" 2>/dev/null || true
pkill -f "python -m sources.temperature.main" 2>/dev/null || true
pkill -f "/tmp/datamesh-pdu" 2>/dev/null || true
pkill -f "datamesh-pdu" 2>/dev/null || true

# Libera portas reservadas pelo sistema
fuser -k 9997/tcp 9998/udp 9999/udp 8080/tcp 50051/tcp >/dev/null 2>&1 || true

# 2. Remove bancos de dados locais e arquivos temporários da demonstração
echo "[2/5] Removendo bancos de dados temporários e logs..."
rm -f /tmp/datamesh-demo.* /tmp/datamesh-pdu
rm -f datamesh.db datamesh.db-wal datamesh.db-shm
rm -f .coverage coverage.xml
rm -rf htmlcov

# 3. Limpa caches de ferramentas e linguagens (Python & Go)
echo "[3/5] Limpando caches de compilação, testes e linters..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
rm -rf .pytest_cache .ruff_cache

if command -v go >/dev/null 2>&1; then
    go clean -cache -testcache 2>/dev/null || true
fi

# 4. Sincroniza ambiente virtual Python
echo "[4/5] Sincronizando dependências Python via uv..."
if command -v uv >/dev/null 2>&1; then
    uv sync --quiet
fi

# 5. Regera os contratos Protocol Buffers (Python e Go)
echo "[5/5] Regerando stubs Protobuf e compilando binário Go..."
bash scripts/build_protos.sh

if command -v go >/dev/null 2>&1; then
    go build -o /tmp/datamesh-pdu ./sources/pdu/cmd/main.go
fi

echo "=========================================================="
echo " [CLEANUP] Ambiente restaurado e reconstruído com sucesso!"
echo "=========================================================="
