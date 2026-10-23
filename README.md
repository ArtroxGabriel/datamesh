# DataMesh DCIM — Gestão de Ambiente Inteligente em Data Center

Sistema distribuído de monitoramento, coleta contínua de telemetria, detecção de eventos críticos e controle de climatização em racks de data center (**Trabalho Prático 1 — Sistemas Distribuídos / Distribuição de Processos e Dados — UFC**).

---

## 1. Arquitetura do Sistema

```
+-----------------------------------------------------------------------------------+
|                                 FONTES DE DADOS                                   |
|                                                                                   |
|  [Ar-Condicionado de Precisão]          [Sensor de Temperatura]        [PDU de Rack] |
|   (Python - Controlável)                (Python - Event-Driven)        (Go - Contínuo)
|   - gRPC Server (:50051 SetControl)     - UDP Telemetria               - UDP Telemetria
|   - UDP Telemetria status               - Disparo Imediato (> 35°C)    - Potência/Corrente
+-----------------------------------------------------------------------------------+
                                         │ UDP Unicast (:9998) / Multicast (239.255.0.1:9999)
                                         ▼
+-----------------------------------------------------------------------------------+
|                                 GATEWAY CENTRAL                                   |
|                                                                                   |
|  • Descoberta Dinâmica de Fontes via UDP Multicast (239.255.0.1:9999)             |
|  • Ingestão de Fluxos UDP de Telemetria & Alertas (:9998)                         |
|  • Armazenamento de Séries Temporais e Consultas Agregadas em SQLite (WAL)        |
|  • Proxy de Comandos de Controle via gRPC Stubs                                   |
|  • Servidor de Sessões TCP com Framing Length-Prefixed Protobuf (:9997)           |
+-----------------------------------------------------------------------------------+
                                         │ TCP (:9997 Length-Prefixed Protobuf)
                                         ▼
+-----------------------------------------------------------------------------------+
|                         CLIENTE WEB (Python / FastAPI)                            |
|                                                                                   |
|  • Comunica-se com o Gateway exclusivamente via Socket TCP + Protobuf             |
|  • Dashboard Web (:8080 HTML + Chart.js) com gráficos de séries temporais         |
|  • Listagem de fontes ativas e detecção passiva de falha (ONLINE / OFFLINE >15s)  |
|  • Envio de parâmetros de operação (ligar/desligar AC, setpoint, ventilação)      |
|  • Execução das 3 consultas analíticas agregadas sobre o histórico                |
+-----------------------------------------------------------------------------------+
```

### Requisitos & Bônus Atendidos
- **Serialização 100% Protocol Buffers:** Contrato único em `proto/datamesh.proto` para descoberta, telemetria UDP, atuação gRPC e sessão TCP.
- **Descoberta Dinâmica via UDP Multicast:** Beacons no grupo `239.255.0.1:9999`.
- **Interoperabilidade Multi-Linguagem (Bônus):** Python 3.12+ (`gateway`, `ac`, `temperature`, `client`) e Go 1.23+ (`pdu`).
- **Persistência e Consultas Históricas (Bônus):** Banco SQLite local no Gateway com suporte a 3 consultas analíticas agregadas (`HOTTEST_RACK`, `AVG_PDU_POWER`, `THERMAL_STABILITY`).
- **Interface Gráfica Web com Séries Temporais (Bônus):** Dashboard FastAPI + `Chart.js` desacoplado via socket TCP length-prefixed (4 bytes big-endian).

---

## 2. Execução Rápida

### Opção A — Demonstração Local Integrada (1 Comando)

Inicia todos os 5 processos (`gateway`, `ac`, `pdu`, `client` e `temperature` com gatilho interativo `[ENTER]` no terminal):

```bash
./scripts/run_demo.sh
# ou via Taskfile:
mise exec -- task demo
```

- Acesse o Dashboard em: **http://localhost:8080**
- Pressione **`[ENTER]`** no terminal para disparar imediatamente uma anomalia térmica crítica (`38.8 °C > 35 °C`).
- Pressione **`Ctrl+C`** para encerrar todos os processos de forma limpa.

### Opção B — Docker Compose (`network_mode: host`)

Construído com builds multi-stage (`uv` slim para Python e binário estático em `scratch` para Go, executando sob usuário não-root `10001:10001`):

```bash
docker compose up --build -d
```

- Acesse o Dashboard em: **http://localhost:8080**
- Para disparar a anomalia térmica interativa (`> 35 °C`) no container do sensor:
  ```bash
  docker attach $(docker compose ps -q temperature)
  # Pressione [ENTER] para enviar o alerta imediato (Ctrl+P, Ctrl+Q para desanexar)
  ```
- Para simular falha/desligamento de uma fonte e observar a transição para `OFFLINE` após 15s:
  ```bash
  docker compose stop pdu
  ```
- Para encerrar:
  ```bash
  docker compose down
  ```

### Opção C — Execução Manual em Terminais Separados

```bash
# Terminal 1 — Gateway Central
uv run python -m gateway.main

# Terminal 2 — Ar-Condicionado de Precisão (Servidor gRPC + Telemetria UDP)
uv run python -m sources.ac.main

# Terminal 3 — Sensor de Temperatura de Rack (Gatilho interativo [ENTER] > 35°C)
uv run python -m sources.temperature.main

# Terminal 4 — PDU de Rack (Go)
mise exec -- go run ./sources/pdu/cmd/main.go

# Terminal 5 — Cliente Web (FastAPI Dashboard em http://localhost:8080)
uv run python -m client.main
```

---

## 3. Verificação, Testes e Qualidade

```bash
# Pipeline completo (compilação Protobuf + linters + typecheck + testes Python & Go >=80% cov)
mise exec -- task check

# Smoke test automatizado ponta a ponta (sobe os 5 processos, valida API/gRPC/Analytics e encerra)
./scripts/run_demo.sh --smoke
```
