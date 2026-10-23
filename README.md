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

### Opção A — Console Interativo de Demonstração (Recomendado para o Vídeo)

Inicia automaticamente o Gateway, o Cliente Web (`http://localhost:8080`) e uma topologia **multi-rack** inicial (`ac-rack-01`, `temp-rack-01`, `temp-rack-02`, `pdu-rack-01`, `pdu-rack-02`), abrindo um **menu interativo no terminal**:

```bash
./scripts/run_demo.sh
# ou via Taskfile:
mise exec -- task demo
```

No menu do terminal você pode controlar toda a demonstração ao vivo:
- **`[1]` 🔥 Disparar anomalia térmica imediata (`> 35°C`):** envia sinal `SIGUSR1` ao sensor escolhido para transmitir imediatamente o alerta crítico (`38.8 °C [ALERTA]`) ao Gateway.
- **`[2]` ➕ Adicionar novo sensor/PDU ao vivo:** instancia `temp-rack-03`, `pdu-rack-03`, etc. em tempo de execução para demonstrar a descoberta dinâmica via beacon UDP Multicast (`239.255.0.1:9999`).
- **`[3]` 💥 Simular falha/desligamento de uma fonte (`ONLINE -> OFFLINE`):** encerra o processo da fonte escolhida para demonstrar a detecção passiva de falha após 15s no Dashboard.
- **`[4]` 🔄 Religar/recuperar uma fonte parada (`OFFLINE -> ONLINE`):** reinicia a fonte em falha.
- **`[5]` 📊 Listar estado atual dos processos da Demo.**
- **`[6]` 📜 Exibir últimas linhas de log (`/tmp/datamesh-demo.log`).**

### Opção B — Execução Manual em Terminais Separados

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
