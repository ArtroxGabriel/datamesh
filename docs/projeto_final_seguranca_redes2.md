# Projeto Final de Redes 2: Segurança em IoT com Servidor Central (DataMesh DCIM)

Documento síntese da proposta, arquitetura, vulnerabilidades e mitigações para a apresentação prática da disciplina de Redes de Computadores 2.

---

## 1. Contexto e Objetivo Acadêmico

- **Instituição:** Universidade Federal do Ceará (UFC).
- **Disciplina:** Redes de Computadores 2 (Módulo de Segurança).
- **Tema:** Segurança em Redes IoT Industriais com Servidor Central (Data Center Infrastructure Management - DCIM).
- **Abordagem Didática:** Apresentação comparativa em dois cenários (*Antes vs. Depois*):
  1. **Cenário Inseguro (`feat/iot-security`):** Apresentação das falhas arquiteturais típicas de redes IoT e execução ao vivo de ataques práticos (pentest/exploit).
  2. **Cenário Seguro (nova branch, i.e., `feat/iot-security-solved`):** Demonstração das contramedidas implementadas (criptografia, HMAC, anti-replay, controle de acesso) e execução dos mesmos ataques sendo barrados em tempo real.

---

## 2. Mapeamento com os Pilares de Segurança

| Pilar da Segurança | Violação no Cenário Atual | Solução no Cenário Seguro |
| :--- | :--- | :--- |
| **Confidencialidade** | Leituras térmicas, elétricas e comandos viajam em texto claro (Protobuf sem cifragem). | Criptografia de canal (TLS no gRPC e TCP; payload cifrado ou HMAC no UDP). |
| **Integridade** | Qualquer nó na rede pode alterar ou forjar pacotes UDP sem detecção pelo Gateway. | Hash com chave secreta (**HMAC-SHA256**) em cada pacote de telemetria. |
| **Autenticidade** | Gateway não valida a origem dos pacotes UDP; Ar-Condicionado aceita comandos gRPC de qualquer IP. | **mTLS (Mutual TLS com certificados X.509)** no gRPC/TCP e assinaturas HMAC com chave secreta no UDP. |
| **Frescor / Anti-Replay** | Pacotes antigos podem ser reenviados sem restrição pelo atacante. | Número de Sequência incremental por dispositivo + Janela de Timestamp estrita. |
| **Disponibilidade** | Invasor desliga o Ar-Condicionado remotamente, gerando risco físico de superaquecimento. | Controle de Acesso estrito no serviço de atuação gRPC (somente o Gateway autenticado pode atuar). |
| **Não-Repúdio** | Dispositivos e operadores não assinam eventos, inviabilizando trilha de auditoria confiável. | Identificação criptográfica individual e registro estruturado de eventos de segurança. |

---

## 3. Cenário 1: Arquitetura Atual (`feat/iot-security-solved`) e Ataques Práticos

O DataMesh na branch `feat/iot-security-solved` foi desenvolvido com foco em distribuição de processos, operando em canais abertos:

- **UDP Multicast (`239.255.0.1:9999`):** Descoberta de fontes sem autenticação de beacon.
- **UDP Unicast (`:9998`):** Ingestão contínua de telemetria em Protobuf puro.
- **gRPC (`:50051`):** Servidor de atuação do AC em modo `insecure_server`.
- **TCP (`:9997`):** Socket com framing de 4 bytes de comprimento em texto claro.

### Ataques Demonstrados (Pasta `scripts/attacks/`)

1. **Sniffing de Telemetria (`sniff_telemetry.py`):**
   - *Mecanismo:* O invasor usa `scapy` ou sockets brutos para interceptar o tráfego da rede local e inspecionar pacotes Protobuf.
   - *Impacto Didático:* Mostra no terminal ou no Wireshark os dados internos confidenciais do data center (temperatura exata dos racks, consumo em Watts e Volts).

2. **Ataque de Repetição com Mascaramento de Anomalia (`replay_masking_attack.py`):**
   - *Mecanismo:* O invasor escuta a rede, captura um pacote legítimo antigo da PDU (ou sensor) reportando operação normal (ex: consumo estável de 1.800 W). Em seguida, injeta uma sobrecarga na PDU real (ex: 8.000 W) e dispara o reenvio contínuo do pacote pacífico antigo em direção ao Gateway.
   - *Impacto Didático (Estilo Stuxnet / "Câmera em Loop"):* O Dashboard do operador continua verde e calmo, mascarando a sobrecarga real que está ocorrendo no hardware.

3. **Sequestro do Atuador gRPC (`hijack_ac.py`):**
   - *Mecanismo:* Um script avulso conecta diretamente na porta `50051` do ar-condicionado e invoca `SetControl(power_on=False)` sem qualquer credencial.
   - *Impacto Didático:* Sabotagem física remota. O invasor desliga o resfriamento dos servidores, provocando alarme e risco de colapso térmico.

---

## 4. Cenário 2: Arquitetura Segura (Nova Branch)

Na nova branch (ex: `feat/iot-security-solved`), o sistema recebe camadas de proteção adequadas para IoT:

### A. Proteção no Fluxo UDP (Telemetria IoT Leve)

Como sensores IoT possuem restrições de processamento para manter handshakes pesados de TLS em streaming UDP contínuo, aplica-se o modelo padrão de IoT industrial:

- **HMAC-SHA256 (Integridade e Autenticidade):** Cada fonte assina o payload do pacote com uma chave pré-compartilhada (PSK). O Gateway valida o hash antes de processar.
- **Anti-Replay com Sequence Number + Timestamp Window:**
  - Cada pacote traz um número de sequência monotônico incremental (`seq_num`).
  - O Gateway descarta pacotes com `seq_num <= last_seen_seq` ou com timestamp com desvio maior que a janela aceitável (ex: ±5 segundos).
  - O script de replay é detectado imediatamente: o pacote antigo é descartado e um alerta de segurança (`SECURITY ALERT: Replay detected`) é registrado.

### B. Proteção no Fluxo gRPC e TCP (Padrão Ouro: mTLS com Certificados X.509)

Para os canais de controle e acesso administrativo (onde roda TCP e gRPC), adota-se o padrão corporativo de redes: **Mutual TLS (mTLS) com Infraestrutura de Chaves Públicas (PKI) local**:

- **Autoridade Certificadora Própria (CA local):** Criamos uma CA raiz (`ca.crt` / `ca.key`) que emite certificados digitais com seus respectivos pares de chaves para cada entidade do sistema:
  - `gateway.crt` / `gateway.key`
  - `ac.crt` / `ac.key`
  - `client.crt` / `client.key`
- **Validação Mútua na Camada de Transporte:**
  - O Ar-Condicionado (servidor gRPC) só aceita conexões de clientes que apresentem um certificado emitido e assinado pela CA confiável (`require_client_auth=True`).
  - O Gateway (servidor TCP) só aceita comandos de operadores/clientes que apresentem o certificado legítimo de cliente.
- **Efeito no Pentest / Ataque de Hijacking:**
  - O script atacante `hijack_ac.py` não possui o certificado assinado pela CA.
  - Ao tentar abrir o canal TLS com o AC ou Gateway, a conexão é abortada no nível de transporte durante o TLS Handshake com o alerta clássico: `SSLV3_ALERT_BAD_CERTIFICATE` / `CERTIFICATE_REQUIRED` ou `UNAUTHENTICATED`.
  - No Wireshark, fica visível o pacote TLS Fatal Alert rejeitando a conexão imediatamente antes de qualquer payload da aplicação transitar.

---

## 5. Roteiro Sugerido para Apresentação em Aula

1. **Introdução Teórica (2 a 3 min):**
   - Apresentar a topologia do DataMesh e o desafio de segurança em IoT industrial (sensores restritos + gateway central + atuadores críticos).
   - Contextualizar os pilares que serão testados: Confidencialidade, Integridade, Autenticidade, Não-repúdio e Disponibilidade.

2. **Demonstração Prática do Cenário Inseguro (4 min):**
   - Subir o sistema na branch `feat/iot-security`.
   - **Demo 1 (Sniffing):** Abrir Wireshark ou o script sniffer e exibir as métricas decodificadas em tempo real.
   - **Demo 2 (Replay Masking):** Provocar anomalia na PDU/sensor e acionar o `replay_masking_attack.py`. Mostrar o Dashboard congelado no estado "seguro" enquanto o terminal do nó real acusa anomalia.
   - **Demo 3 (AC Hijacking):** Rodar `hijack_ac.py` e desligar o ar-condicionado remotamente.

3. **Demonstração Prática do Cenário Seguro (4 min):**
   - Alternar para a branch protegida (`feat/iot-security-solved`).
   - Rodar novamente os mesmos scripts de ataque:
     - O sniffer agora exibe dados cifrados/ilegíveis.
     - O script de replay é descartado pelo Gateway com log explícito de rejeição por número de sequência/timestamp, mantendo o alerta real visível.
     - O script de hijacking do AC falha com `UNAUTHENTICATED`.

4. **Conclusão e Aprendizados (2 min):**
   - Trade-offs de segurança em IoT: overhead de rede e CPU vs. segurança robusta.
   - Importância do princípio de defesa em profundidade em ambientes industriais e data centers.
