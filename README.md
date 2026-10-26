# DataMesh DCIM

O DataMesh DCIM monitora racks de um data center e controla o ar-condicionado que os resfria. DCIM é a sigla de *Data Center Infrastructure Management*, o nome dado a sistemas que acompanham energia e climatização de um data center.

O projeto é o Trabalho 1 da disciplina Sistemas Distribuídos / Distribuição de Processos e Dados (UFC, Prof. Dr. Paulo A. L. Rego). Ele usa sockets TCP e UDP, UDP multicast, Protocol Buffers e gRPC, com processos escritos em Python e em Go.

### Equipe

- Antonio Gabriel Carmo Rego, matrícula `539628`
- Lucas Lopes de Sousa, matrícula `537512`

### Sumário

- [1. Arquitetura](#1-arquitetura)
- [2. Módulos](#2-módulos)
- [3. Como rodar](#3-como-rodar)
- [4. Testes e qualidade](#4-testes-e-qualidade)

---

# 1. Arquitetura

O sistema tem três partes que rodam em processos separados. As fontes de dados simulam equipamentos, o Gateway concentra tudo e o Cliente mostra os dados ao usuário. Todas as mensagens trocadas pela rede são serializadas com Protocol Buffers, um formato binário definido no arquivo `proto/datamesh.proto`.

```
+-----------------------------------------------------------------------------------+
|                                 FONTES DE DADOS                                   |
|                                                                                   |
|  [Ar-Condicionado de Precisão]          [Sensor de Temperatura]        [PDU de Rack] |
|   (Python, controlável)                 (Python, envia alertas)        (Go, contínua)
|   - Servidor gRPC (:50051 SetControl)   - Telemetria UDP               - Telemetria UDP
|   - Telemetria UDP                      - Alerta imediato (> 35 °C)    - Potência e corrente
+-----------------------------------------------------------------------------------+
                                         │ UDP unicast (:9998) e multicast (239.255.0.1:9999)
                                         ▼
+-----------------------------------------------------------------------------------+
|                                 GATEWAY                                           |
|                                                                                   |
|  - Descoberta de fontes por UDP multicast (239.255.0.1:9999)                      |
|  - Recebe telemetria e alertas por UDP (:9998)                                    |
|  - Guarda as leituras em SQLite e calcula as consultas agregadas                  |
|  - Repassa comandos ao ar-condicionado por gRPC                                   |
|  - Atende o Cliente por TCP com mensagens prefixadas pelo tamanho (:9997)         |
+-----------------------------------------------------------------------------------+
                                         │ TCP (:9997)
                                         ▼
+-----------------------------------------------------------------------------------+
|                         CLIENTE WEB (Python / FastAPI)                            |
|                                                                                   |
|  - Fala com o Gateway só por TCP e Protobuf                                       |
|  - Dashboard (:8080, HTML e Chart.js) com gráficos das leituras                   |
|  - Lista as fontes agrupadas por tipo, com estado ONLINE ou OFFLINE               |
|  - Liga e desliga o ar-condicionado e ajusta setpoint e ventilação                |
|  - Executa as 3 consultas agregadas sobre o histórico                             |
+-----------------------------------------------------------------------------------+
```

### Protocolos

- UDP multicast (`239.255.0.1:9999`). Ao iniciar, e depois a cada 5 s, o Gateway envia um `DiscoveryRequest` com seu IP e a porta UDP de telemetria. Cada fonte responde com um `DeviceInfo`, que traz ID, tipo, IP, porta gRPC e estado inicial. As fontes só começam a mandar telemetria depois de receber esse pedido.
- UDP unicast (`:9998`). As fontes mandam pacotes `TelemetryPacket` periódicos. O sensor de temperatura também manda um pacote na hora quando passa de 35 °C.
- gRPC (`:50051`). O Gateway chama `AirConditionerService.SetControl` para mudar o estado do ar-condicionado. A resposta traz o estado atualizado da fonte.
- TCP (`:9997`). O Cliente e o Gateway trocam `ClientRequest` e `ClientResponse`. Antes de cada mensagem vão 4 bytes (`uint32` *big-endian*) com o tamanho dela. Isso é preciso porque o TCP entrega um fluxo de bytes sem separar as mensagens.

---

# 2. Módulos

### 2.1. Contrato e framing (`proto/` e `common/`)

O arquivo `proto/datamesh.proto` define todas as mensagens e o serviço gRPC num só lugar, para o Python e o Go usarem o mesmo contrato.

- A descoberta usa `DiscoveryRequest`, `DeviceInfo` e `DeviceType` (`TEMPERATURE_SENSOR`, `RACK_PDU`, `AIR_CONDITIONER`).
- A telemetria usa `TelemetryPacket`, com `temperature_c`, `target_temp_c`, `fan_speed_pct`, `power_watts`, `current_amps`, `voltage_volts`, `ac_power_on` e a marca de alerta `is_alert`.
- O controle usa o serviço `AirConditionerService`, com `SetControl(ACControlRequest) returns (ACControlResponse)`.
- O Cliente usa `ClientRequest`, `ClientResponse` e `AnalyticsResult`. As consultas são `HOTTEST_RACK`, `AVG_PDU_POWER` e `THERMAL_STABILITY`.

O `common/framing.py` envia e lê mensagens no TCP com `send_proto` e `recv_proto`. A leitura usa `recv_exact` para juntar os pedaços até completar o tamanho anunciado no cabeçalho.

### 2.2. Gateway (`gateway/`)

O Gateway registra as fontes, guarda as leituras e repassa comandos.

- `gateway/registry.py` mantém em memória a lista de fontes. Uma fonte que fica mais de 15 s (`OFFLINE_THRESHOLD_MS`) sem mandar pacotes aparece como `OFFLINE`. Quando o anúncio chega sem IP, o Gateway usa o endereço de onde o pacote veio.
- `gateway/storage/` guarda as leituras em SQLite, no modo WAL, que deixa ler e escrever ao mesmo tempo. Ali ficam as 3 consultas, todas sobre uma janela de tempo escolhida pelo usuário.
  1. `HOTTEST_RACK` devolve o sensor com a maior temperatura registrada.
  2. `AVG_PDU_POWER` devolve a potência média das PDUs em watts.
  3. `THERMAL_STABILITY` devolve a média e o desvio padrão das temperaturas dos racks.
- `gateway/service.py` cuida das threads de UDP, dos pedidos de descoberta e do servidor TCP. O `gateway/proxy.py` tem o cliente gRPC (`GrpcACControlProxy`) que fala com o ar-condicionado.

### 2.3. Ar-condicionado de precisão (`sources/ac/`)

É a fonte controlável. O `sources/ac/actuator.py` sobe um servidor gRPC na porta 50051. O comando `SetControl` muda o estado de energia (`power_on`), a temperatura alvo (`target_temp_c`) e a velocidade do ventilador (`fan_speed_pct`).

A simulação aproxima aos poucos a temperatura da sala do *setpoint*. Desligado, o aparelho deixa a sala voltar à temperatura ambiente. O consumo elétrico acompanha a velocidade do ventilador.

### 2.4. Sensor de temperatura de rack (`sources/temperature/`)

É a fonte que manda dados na hora quando acontece um evento. O `sources/temperature/sensor.py` envia leituras periódicas em torno da temperatura base do rack (`BASE_TEMP_C`).

A anomalia é disparada com `ENTER` no terminal do sensor ou com o sinal `SIGUSR1`, que o console da demonstração usa. O sensor chama `trigger_anomaly(temp_c=38.8)` e manda na hora um pacote com `is_alert=True`, sem esperar o próximo envio periódico. O rack fica quente por 20 s (`ANOMALY_HOLD_SEC`) e depois esfria aos poucos (`ANOMALY_DECAY_SEC`, 10 s). O alerta só termina abaixo de 33 °C, para não ligar e desligar quando a leitura oscila perto de 35 °C.

### 2.5. PDU de rack em Go (`sources/pdu/`)

A PDU é a unidade que distribui energia aos servidores do rack. Aqui ela é a fonte contínua, escrita em Go para usar o mesmo contrato Protobuf em outra linguagem. O `sources/pdu/pdu.go` usa o código gerado em `gen/go`. A PDU escuta o multicast com `net.ListenMulticastUDP`, aprende o endereço do Gateway e manda potência (W), corrente (A) e tensão (V) por UDP.

### 2.6. Cliente web (`client/`)

O Cliente é um processo Python com FastAPI. O navegador fala HTTP com ele, e ele fala com o Gateway por TCP. Ele nunca acessa o SQLite nem as fontes.

- `client/gateway_client.py` (`TCPGatewayClient`) faz as quatro operações (`list_devices`, `get_history`, `control_ac` e `query_analytics`), cada uma numa conexão TCP com o Gateway na porta 9997.
- `client/static/index.html` é o dashboard, atualizado a cada 2 s. Ele agrupa as fontes por tipo, destaca em vermelho os sensores em alerta e marca as fontes paradas como `OFFLINE`. Também mostra os gráficos, o painel de controle do ar-condicionado e as 3 consultas.
- `client/events.py` e `client/static/events.html` formam a página `/events`, uma linha do tempo do sistema. Ela mostra a entrada de fontes, as mudanças entre `ONLINE` e `OFFLINE` e o início e o fim dos alertas. Também mostra os comandos enviados ao ar-condicionado e as consultas executadas. Uma thread do Cliente consulta o Gateway a cada 1 s, então a lista cobre a demonstração inteira mesmo que a página seja aberta depois.

---

# 3. Como rodar

### Pré-requisitos

O projeto usa Python 3.12+ (gerenciado pelo `uv`) e Go 1.23+ (gerenciado pelo `mise`). Este comando instala as ferramentas e as dependências.

```bash
mise install && uv sync
```

### Console de demonstração

O script `scripts/run_demo.sh` compila a PDU, sobe o Gateway e o Cliente Web (`http://localhost:8080`) e inicia cinco fontes (`ac-01-carnot`, `temp-01-turing`, `temp-02-curie`, `pdu-01-tesla` e `pdu-02-faraday`). As fontes sobem sem o endereço do Gateway e aparecem no dashboard depois do primeiro pedido de descoberta, em até 5 s.

```bash
./scripts/run_demo.sh
# ou pelo Taskfile
mise exec -- task demo
```

O menu do console tem estas opções.

- `[1]` dispara uma anomalia num sensor escolhido, que manda na hora um alerta de 38,8 °C.
- `[2]` inicia um sensor ou uma PDU nova, com nome gerado (por exemplo `temp-03-frosty-fermi`). Ela entra no sistema pela descoberta.
- `[3]` encerra uma fonte para simular falha. Depois de 15 s sem telemetria, o Gateway a marca como `OFFLINE`.
- `[4]` religa uma fonte parada, que volta a `ONLINE`.
- `[5]` mostra o estado dos processos.
- `[6]` mostra as últimas 15 linhas do log (`/tmp/datamesh-demo.log`).
- `[q]` encerra todos os processos.

### Um processo por terminal

```bash
# Terminal 1: Gateway (TCP :9997, UDP :9998, multicast 239.255.0.1:9999)
uv run python -m gateway.main

# Terminal 2: ar-condicionado (gRPC :50051)
uv run python -m sources.ac.main

# Terminal 3: sensor de temperatura (ENTER dispara a anomalia)
uv run python -m sources.temperature.main

# Terminal 4: PDU em Go
mise exec -- go run ./sources/pdu/cmd/main.go

# Terminal 5: Cliente Web (http://localhost:8080)
uv run python -m client.main
```

### Rodando em mais de uma máquina

Por padrão o Gateway anuncia o endereço `127.0.0.1`, que só funciona quando tudo roda na mesma máquina. Para fontes em outras máquinas da rede, informe o IP do Gateway que elas devem usar.

```bash
GATEWAY_ADVERTISED_IP=192.168.0.10 uv run python -m gateway.main
```

O ar-condicionado não precisa de configuração, porque o Gateway usa o endereço de origem do anúncio para chamar o gRPC. Se ele estiver atrás de NAT ou tiver mais de uma interface, defina `AC_ADVERTISED_IP`. Para pular a descoberta e fixar o Gateway numa fonte, defina `GATEWAY_HOST` e `GATEWAY_PORT`.

---

# 4. Testes e qualidade

Os testes Python usam `pytest` e exigem no mínimo 80% de cobertura. A PDU tem testes em Go. O `ruff` confere estilo e formatação, o `ty` confere os tipos do Python e o `go vet` analisa o código Go.

```bash
# Gera o código do proto, roda lint, checagem de tipos e todos os testes
mise exec -- task check

# Só os testes Python, com relatório de cobertura
uv run pytest

# Só os testes Go da PDU
mise exec -- go test -v ./sources/pdu/...

# Sobe todos os processos, testa descoberta, gRPC e consultas, e encerra
./scripts/run_demo.sh --smoke
```
