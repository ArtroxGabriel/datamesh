## Project Overview

- Gestão de Ambiente Inteligente (DataMesh DCIM -- Data Center Infrastructure Management).
- Sistema distribuído para monitoramento, coleta de telemetria contínua, detecção de eventos e controle de climatização em racks de data center.
- Trabalho prático 1 da disciplina de Sistemas Distribuídos / Distribuição de Processos e Dados (UFC - Prof. Dr. Paulo A. L. Rego).
- Estágio: MVP acadêmico modular e desacoplado.

## Tech Stack

- Linguagens: Python 3.12+ (gerenciado via `uv`) e Go 1.23+ (gerenciado via `mise`).
- Interface Web (Cliente): `FastAPI` + `uvicorn` no backend do Cliente e página single-page com `Chart.js` para visualização de séries temporais.
- Serialização & RPC: Protocol Buffers v3 (`protoc` 36+) e gRPC.
- Rede e Transporte:
  - UDP Multicast para descoberta dinâmica de fontes (`239.255.0.1:9999`).
  - UDP Unicast para streaming contínuo de telemetria e alertas imediatos orientados a eventos.
  - TCP (com framing length-prefixed: 4 bytes big-endian + payload Protobuf) entre Cliente e Gateway.
  - gRPC entre Gateway e fontes atuadoras (Ar-Condicionado de Precisão).
- Persistência: SQLite local no Gateway para armazenamento de séries temporais e suporte a consultas analíticas agregadas.
- Automação: `Taskfile.yml` / `mise` / `uv`.

## File Structure

docs/, proto/, gen/, gateway/, sources/, client/, scripts/

- `docs/` — Documentação do projeto, especificação da disciplina e objetivos detalhados.
- `proto/` — Definições formais de contratos Protocol Buffers (`.proto`) para mensagens e serviços gRPC.
- `gen/` — Código gerado pelo compilador `protoc` para Python e Go (não editar manualmente).
- `gateway/` — Processo central: ingestão UDP, discovery multicast, proxy gRPC, servidor TCP e persistência SQLite.
- `sources/` — Processos independentes das fontes de dados heterogêneas (AC, sensor térmico, PDU).
- `sources/ac/` — Ar-Condicionado de Precisão (Python): servidor gRPC de atuação e streaming UDP.
- `sources/temperature/` — Sensor de temperatura de rack (Python): envio UDP contínuo e disparos imediatos por anomalia (> 35°C).
- `sources/pdu/` — PDU de Rack (Go): telemetria de potência/corrente/tensão via UDP contínuo.
- `client/` — Processo do Cliente Web (Python/`FastAPI`) que serve o Dashboard de séries temporais via HTTP ao navegador e se comunica exclusivamente via socket TCP (framing Protobuf) com o Gateway.

## Common Commands

- Gerar código Protobuf (Python & Go):
  `mise exec -- task proto` ou `./scripts/build_protos.sh`
- Executar Gateway localmente:
  `uv run python -m gateway.main`
- Executar Fontes localmente:
  - AC: `uv run python -m sources.ac.main`
  - Sensor: `uv run python -m sources.temperature.main`
  - PDU: `mise exec -- go run ./sources/pdu/cmd/main.go`
- Executar Cliente Web (Dashboard):
  `uv run python -m client.main` (acessível em `http://localhost:8080`)
- Testes:
  - Python: `uv run pytest`
  - Go: `mise exec -- go test ./sources/pdu/...`
- Linters, Checagem de Tipos & Formatação:
  - Python: `uv run ty check` (type checking da Astral: <https://docs.astral.sh/ty/>), `uv run ruff check .` e `uv run ruff format .`
  - Go: `mise exec -- go vet ./sources/pdu/...` e `mise exec -- gofmt -w ./sources/pdu`

## Environment / Setup

- Ferramentas locais gerenciadas pelo `mise`: `uv`, `go`, `task`, `protoc`, `protoc-gen-go` (e opcionalmente `ty`).
- Instalar dependências da toolchain:
  `mise install`

## Code Quality

- Seguir convenções do repositório: funções pequenas (4-20 linhas), SRP, nomes descritivos.
- Python: tipagem estrita com Type Hints checada via `ty` (Astral) e `ruff`, imutabilidade onde aplicável.
- Go: padrão idiomático, tratamento explícito de erros, `go vet` e `gofmt`.
- Protos: estilo oficial Google Protobuf (snake_case para campos, PascalCase para mensagens/serviços).

## Architecture Conventions

- Contrato Protobuf único (`proto/datamesh.proto`): centraliza mensagens UDP, TCP e definições gRPC para evitar complexidade de imports entre Python e Go.
- Gateway é o intermediário único para clientes: o Cliente Web nunca conversa diretamente com as Fontes nem acessa o SQLite; o navegador fala HTTP com o processo `client/`, e o `client/` fala exclusivamente via socket TCP (framing Protobuf) com o Gateway.
- Framing TCP obrigatório: delimitação explícita por tamanho do payload (`uint32` big-endian).
- Fontes são processos desacoplados com resiliência a falhas e reconexão.
- Fontes sobem sem endereço do Gateway e só transmitem depois do primeiro `DiscoveryRequest`. `GATEWAY_HOST` fixa um endereço e pula essa espera.
- O Gateway anuncia `127.0.0.1` por padrão. Com fontes em outras máquinas, defina `GATEWAY_ADVERTISED_IP`.
- Detecção de falha passiva no Gateway: baseada no timestamp `last_seen` dos pacotes UDP de cada fonte (`> 15s` sem telemetria marca a fonte como `OFFLINE`).
- Simulação de anomalia sob demanda: `sources/temperature` permite gatilho interativo no terminal para disparar leitura `> 35°C` imediatamente via UDP.
- O banco SQLite reside exclusivamente no Gateway e armazena leituras com timestamp, device_id e valores métricos normalizados.

## Known Gotchas

- Diretório `gen/`: nunca editar manualmente os arquivos gerados pelo `protoc`.
- Sockets TCP: streaming contínuo exige sempre leitura do cabeçalho de 4 bytes de comprimento para ler exatamente o tamanho do frame Protobuf.

## Agent Do's and Don'ts

- Não acoplar o Cliente diretamente a bancos ou fontes; respeitar a topologia distribuída.
- Manter documentação e comentários focados no "porquê" das decisões técnicas.
- Não remover anotações arquiteturais ou decisões registradas neste documento.
