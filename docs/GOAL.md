# Gestão de Ambiente Inteligente (DataMesh DCIM -- Data Center Infrastructure Management)

## Especificação e Objetivos do Trabalho 1 — Sistemas Distribuídos

Este documento descreve o propósito, a visão geral e os domínios de aplicação do projeto prático da disciplina de **Sistemas Distribuídos / Distribuição de Processos e Dados** (Prof. Dr. Paulo A. L. Rego).

---

## 1. Propósito e Objetivos do Projeto

O objetivo principal é construir um **sistema distribuído de monitoramento e controle**, com foco em coleta, agregação e análise de dados em tempo real, composto por três entidades principais:

1. **Fontes de Dados Distribuídas (Processos Independentes):** Dispositivos e sensores heterogêneos simulados (sensores contínuos, sensores orientados a eventos e atuadores controláveis).
2. **Gateway Central:** Concentrador que orquestra a descoberta dinâmica, ingere fluxos de telemetria, persiste leituras e atua como intermediário para comandos e análises.
3. **Cliente (Dashboard Web):** Processo independente em Python que conecta ao Gateway via socket TCP (Protobuf) e expõe uma interface gráfica Web para inspecionar topologia, visualizar séries temporais em tempo real, enviar atuações e disparar consultas analíticas agregadas.

### Conceitos de Sistemas Distribuídos Consolidados no Projeto

* **Comunicação por Sockets TCP e UDP:**
  * **TCP:** Utilizado entre o Cliente e o Gateway para controle confiável de sessão e requisição/resposta (framing *Length-Prefixed Protobuf*).
  * **UDP:** Utilizado pelas Fontes de Dados para streaming contínuo de telemetria e envio de alertas ao Gateway com baixa sobrecarga.
* **Descoberta Dinâmica de Dispositivos (UDP Multicast):**
  * Ao iniciar (e periodicamente), o Gateway envia uma requisição via multicast UDP informando seu endereço e porta de ingestão UDP; as fontes ativas respondem via Protobuf informando seu **tipo**, **IP e porta** (incluindo a porta do servidor gRPC para fontes controláveis) e **estado operacional inicial**.
* **Serialização Padronizada (Protocol Buffers):**
  * Todas as mensagens trocadas no sistema (TCP, UDP e gRPC) utilizam Protocol Buffers como formato de serialização estrito e eficiente.
* **Invocação Remota de Procedimentos (gRPC):**
  * Atuação do Gateway sobre fontes controláveis realizada por serviços gRPC definidos formalmente em contratos `.proto`.
* **Persistência e Processamento Analítico:**
  * Armazenamento histórico das leituras em banco relacional local (SQLite) para execução de consultas agregadas (médias móveis, extremos, desvios).
* **Interoperabilidade Multi-Linguagem:**
  * Coexistência de serviços em ecossistemas diferentes (Python 3 e Go) comunicando-se de forma transparente via Protocol Buffers.

---

## 2. Domínio Escolhido: Monitoramento e Climatização de Data Center (DCIM)

O sistema foi instanciado no domínio de **Data Center Infrastructure Management (DCIM)**, monitorando a integridade física e o consumo energético de racks de servidores e controlando o sistema de climatização.

### Componentes Instanciados

```
+-----------------------------------------------------------------------------------+
|                                 FONTES DE DADOS                                   |
|                                                                                   |
|  [Ar-Condicionado de Precisão]          [Sensor de Temperatura]        [PDU de Rack] |
|   (Python - Controlável)                (Python - Event-Driven)        (Go - Contínuo)
|   - gRPC Server (Setpoints/Power)       - UDP Telemetria               - UDP Telemetria
|   - UDP Telemetria status               - Disparo Imediato (> 35°C)    - Potência/Corrente
+-----------------------------------------------------------------------------------+
                                         │ UDP / Multicast
                                         ▼
+-----------------------------------------------------------------------------------+
|                                 GATEWAY CENTRAL                                   |
|                                                                                   |
|  • Descoberta de Fontes via Multicast UDP                                         |
|  • Ingestão de Fluxos UDP Telemetria & Alertas                                     |
|  • Armazenamento e Histórico em SQLite                                            |
|  • Proxy de Comandos de Controle via gRPC Stubs                                  |
|  • Servidor de Sessões TCP com Framing Protobuf                                   |
+-----------------------------------------------------------------------------------+
                                         │ TCP (Length-Prefixed Protobuf)
                                         ▼
+-----------------------------------------------------------------------------------+
|                         CLIENTE WEB (Python / FastAPI)                            |
|                                                                                   |
|  • Comunica-se com o Gateway exclusivamente via Socket TCP + Protobuf             |
|  • Dashboard Web (HTML + Chart.js) com gráficos de séries temporais               |
|  • Listagem de fontes ativas e respectivos estados (ONLINE / OFFLINE)             |
|  • Envio de parâmetros de operação (ligar/desligar AC, setpoint, rotação)         |
|  • Execução de consultas analíticas agregadas sobre o histórico                   |
+-----------------------------------------------------------------------------------+
```

### Fontes de Dados Mínimas do Domínio

1. **Ar-Condicionado de Precisão (Fonte Controlável — Python):**
   * **Controle:** Expõe servidor gRPC para ligar/desligar unidade, ajustar temperatura alvo (*setpoint*) e velocidade dos ventiladores.
   * **Telemetria:** Envia via UDP suas métricas operacionais (temperatura ambiente atual, setpoint em vigor e potência de ventilação).
2. **Sensor de Temperatura de Rack (Fonte Orientada a Eventos — Python):**
   * **Contínuo:** Envia leituras térmicas via UDP periodicamente.
   * **Disparo Imediato por Evento Crítico:** Ao detectar ultrapassagem de limiar de segurança (ex: > 35°C), envia imediatamente um pacote de alerta prioritário ao Gateway sem esperar pelo timer periódico.
3. **PDU de Rack (Fonte Contínua — Go):**
   * Envia fluxo periódico via UDP reportando potência ativa (Watts), corrente (Amperes) e tensão dos servidores alimentados. Demonstra interoperabilidade e uso de mais de uma linguagem de programação.

### Consultas Analíticas Agregadas Mínimas

1. **Rack mais quente:** Identifica o sensor/rack com o pico térmico registrado na janela de tempo especificada.
2. **Consumo médio de potência:** Calcula a média de consumo energético (kW/Watts) das PDUs na última hora/período selecionado.
3. **Estabilidade e dispersão térmica:** Calcula a média e o desvio padrão das temperaturas para avaliar a estabilidade do fluxo de ar e arrefecimento.

---

## 3. Entregáveis e Critérios de Conclusão (Prazo: 25/10/2026)

* **Código-fonte:** Implementação modular em repositório público (GitHub/GitLab) ou arquivo `.zip` com separação de responsabilidades (contratos `.proto`, fontes, gateway, cliente e utilitários).
* **Slides de Apresentação:** Apresentação do domínio DCIM e detalhes de implementação das três partes (Fontes, Gateway e Cliente), com foco explícito no formato das mensagens Protobuf trocadas, na definição dos serviços gRPC e nas linguagens, frameworks e bibliotecas utilizados.
* **Vídeo Demonstrativo (até 7 min):**
  * Inicialização dos processos e descoberta dinâmica via multicast.
  * Streaming contínuo de telemetria via UDP e recepção de alertas imediatos por limiar.
  * Listagem de estados e envio de comandos de atuação via gRPC a partir do Cliente.
  * Execução das 3 consultas analíticas agregadas sobre o histórico no Gateway.
  * Demonstração de falha/desligamento de uma fonte de dados e tratamento pelo Gateway.
* **Bônus Atendidos (100% da pontuação extra):**
  * Uso de mais de uma linguagem de programação (Python 3 e Go).
  * Persistência de dados em banco de dados (SQLite) no Gateway com suporte a consultas sobre o histórico de leituras.
  * Cliente com interface gráfica Web e visualização de séries temporais dos dados coletados.

---

## 4. Decisões Arquiteturais Simplificadas e Plano de Implementação (MVP)

Para manter o projeto enxuto, evolutivo e fácil de demonstrar no vídeo de 7 minutos:

### Decisões de Simplificação
1. **Contrato Protobuf Único (`proto/datamesh.proto`):** Todas as mensagens (Discovery, Telemetria UDP, Requisições/Respostas TCP do Cliente, incluindo histórico para séries temporais) e o serviço gRPC do Ar-Condicionado ficam em um único arquivo `.proto`, evitando problemas de import relativo entre Python e Go.
2. **Cliente Web desacoplado via TCP (`FastAPI` + `Chart.js`):** O processo `client/` atua como um servidor Web em Python (`FastAPI` + `uvicorn`) que entrega uma página única com gráficos (`Chart.js`), mas **toda comunicação entre Cliente e Gateway ocorre estritamente via Socket TCP puro com framing Protobuf** (sem acesso direto ao SQLite e sem HTTP no Gateway).
3. **Simulação de Anomalia sob Demanda (> 35°C):** O sensor de temperatura envia leituras periódicas normais, mas aceita um comando interativo no próprio terminal (ex: pressionar `Enter`) para disparar imediatamente um pico térmico `> 35°C` durante a gravação da demonstração.
4. **Detecção Passiva de Falha/Desligamento (`last_seen`):** O Gateway registra o timestamp do último pacote UDP recebido de cada fonte. Se `agora - last_seen > 15s`, a fonte é exibida como `OFFLINE` na listagem do Cliente (atendendo ao requisito de demonstrar falha/desligamento sem precisar de healthchecks ativos).
5. **Execução Local Primeiro (`Taskfile.yml` + `uv` + `go run`):** Todo o desenvolvimento e validação serão feitos com processos locais primeiro; Docker Compose fica como etapa opcional caso sobre tempo após o MVP estar 100% funcional.

### Ordem de Implementação
1. **Etapa 1 — Contrato e Base:** Criar `proto/datamesh.proto`, configurar `pyproject.toml`, `go.mod` e `Taskfile.yml`, e gerar código em `gen/python` e `gen/go`.
2. **Etapa 2 — Gateway Central (`gateway/`):** Persistência SQLite (tabela única de leituras), descoberta via UDP Multicast (`239.255.0.1:9999`), ingestão de telemetria/alertas UDP, cliente gRPC para o AC e servidor TCP (framing de 4 bytes big-endian) para o Cliente.
3. **Etapa 3 — Fontes de Dados (`sources/`):**
   * `sources/temperature` (Python): responde ao multicast, envia temperatura periódica via UDP e dispara alerta imediato `> 35°C` sob demanda.
   * `sources/ac` (Python): responde ao multicast, expõe servidor gRPC de atuação e envia telemetria via UDP.
   * `sources/pdu` (Go): responde ao multicast e envia telemetria de potência/corrente via UDP.
4. **Etapa 4 — Cliente Web (`client/`):** Servidor Web em Python (`FastAPI`) conectado via socket TCP (framing Protobuf) ao Gateway + Dashboard single-page (`HTML` + `Chart.js`) para listar fontes (`ONLINE`/`OFFLINE`), visualizar gráficos de séries temporais, enviar comandos gRPC ao AC via Gateway e executar as 3 consultas analíticas agregadas.
