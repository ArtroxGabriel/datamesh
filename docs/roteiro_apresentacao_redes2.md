# Roteiro e Visão Geral da Demonstração — Redes 2 (Segurança em IoT)

Guia de alto nível para a apresentação prática do projeto **DataMesh DCIM** na disciplina de Redes de Computadores 2 (UFC), comparando o cenário vulnerável (`feat/iot-security`) com o cenário protegido (`feat/iot-security-solved`).

---

## 1. Visão Geral da Narrativa (Antes vs. Depois)

```mermaid
flowchart LR
    subgraph V["Cenário 1 — feat/iot-security (Aberto)"]
        direction TB
        V_SRC["Fontes IoT (PDU Go, Sensor, AC)"]
        V_GW["Gateway Central"]
        V_CLI["Cliente Web / Dashboard"]
        V_SRC -->|"UDP Texto Claro (sem HMAC/seq)"| V_GW
        V_GW -->|"gRPC Insecure :50051"| V_SRC
        V_CLI <-->|"TCP Texto Claro :9997"| V_GW
    end

    subgraph S["Cenário 2 — feat/iot-security-solved (Protegido)"]
        direction TB
        S_SRC["Fontes IoT (PDU Go, Sensor, AC)"]
        S_GW["Gateway Central"]
        S_CLI["Cliente Web / Dashboard"]
        S_SRC -->|"UDP + HMAC-SHA256 + Seq/Timestamp"| S_GW
        S_GW -->|"gRPC + mTLS (X.509)"| S_SRC
        S_CLI <-->|"TCP + mTLS (X.509)"| S_GW
    end
```

### Estrutura de Tempo (~12 minutos)

| Bloco | Duração | Foco | Branch |
| :--- | :---: | :--- | :--- |
| **1. Contextualização** | 2 min | Topologia IoT com servidor central e pilares de segurança | — |
| **2. Cenário Vulnerável** | 4 min | Evidenciar falhas práticas de confidencialidade, frescor e autenticação | `feat/iot-security` |
| **3. Cenário Protegido** | 4 min | Mostrar PKI/mTLS + HMAC/Anti-Replay barrando os mesmos vetores | `feat/iot-security-solved` |
| **4. Trade-offs e Fechamento** | 2 min | Custo de criptografia em IoT restrito vs. defesa em profundidade | — |

---

## 2. Organização da Tela na Apresentação

Para a turma acompanhar em tempo real sem troca constante de janelas:

- **Metade esquerda (Navegador):**
  - Dashboard principal (`http://localhost:8080`) com gráficos de potência/temperatura e status do AC.
  - Aba de topologia (`http://localhost:8080/network`) e eventos (`http://localhost:8080/events`).
- **Metade direita (2 terminais + Wireshark):**
  - **Terminal 1:** Console interativo da demo (`mise exec -- task demo` / `bash scripts/run_demo.sh`), permitindo disparar anomalia térmica `[1]` e sobrecarga elétrica de ~8000 W na PDU `[2]`.
  - **Terminal 2 / Wireshark:** Inspeção de pacotes na interface de loopback (`lo`) com filtro `udp.port == 9998 || tcp.port == 9997 || tcp.port == 50051` e testes de validação.

---

## 3. Roteiro Passo a Passo

### Ato 1 — Contexto e Arquitetura (2 min)
1. Explicar o papel de cada componente do DataMesh DCIM:
   - **Fontes heterogêneas:** PDU de Rack (Go), Sensor Térmico (Python) e Ar-Condicionado de Precisão (Python + gRPC).
   - **Servidor Central (Gateway):** descoberta via UDP multicast, ingestão UDP unicast, persistência SQLite, proxy gRPC e servidor TCP para o cliente.
   - **Cliente Web:** dashboard FastAPI + Chart.js.
2. Conectar com a disciplina: em ambientes IoT/industriais, o modelo de comunicação mistura **fluxo leve contínuo (UDP)** com **comandos críticos de atuação (gRPC/TCP)**. Sem proteção, cada protocolo expõe um pilar diferente da segurança.

---

### Ato 2 — Demonstração no Cenário Vulnerável (`feat/iot-security`) (4 min)

Subir o ambiente com:
```bash
git checkout feat/iot-security
mise exec -- task demo
```

#### Ponto A — Falta de Confidencialidade (Sniffing)
- **O que mostrar:** Abrir o Wireshark (ou `tshark`) filtrando `udp.port == 9998 || tcp.port == 9997`.
- **O que a turma vê:** Os payloads Protobuf trafegam em texto claro; identificadores de dispositivos (`pdu-01-tesla`, `temp-01-turing`, `ac-01-carnot`) e métricas operacionais são legíveis diretamente no tráfego capturado.
- **Pilar violado:** **Confidencialidade**.

#### Ponto B — Falta de Integridade e Frescor (Mascaramento por Replay)
- **O que mostrar:**
  1. Mostrar a PDU `pdu-01-tesla` operando normalmente (~1400 W) e explicar que um pacote legítimo dessa leitura pode ser capturado da rede.
  2. No console da demo, selecionar a opção **`[2] Disparar sobrecarga elétrica (~8000 W) em uma PDU`** — o processo real da PDU entra em estado de sobrecarga crítica (`IsAlert=true`, ~8000 W por 30 s).
  3. Explicar/demonstrar o efeito "câmera em loop" (estilo Stuxnet): como o Gateway não valida assinatura, número de sequência nem janela de timestamp, reenviar o pacote antigo de ~1400 W faz o Gateway sobrescrever o estado exibido no Dashboard, ocultando a sobrecarga real.
- **Pilares violados:** **Integridade**, **Autenticidade** e **Frescor (Anti-Replay)**.

#### Ponto C — Falta de Autenticação na Atuação (gRPC Aberto)
- **O que mostrar:** O serviço `AirConditionerService` na porta `50051` roda sem TLS e sem autenticação mútua. Qualquer processo na rede local pode chamar `SetControl(power_on=false)` diretamente, ignorando o Gateway.
- **O que a turma vê:** O ar-condicionado `ac-01-carnot` é desligado no Dashboard sem qualquer credencial ou auditoria de quem emitiu o comando.
- **Pilares violados:** **Autenticidade**, **Controle de Acesso**, **Disponibilidade** e **Não-Repúdio**.

---

### Ato 3 — Demonstração no Cenário Protegido (`feat/iot-security-solved`) (4 min)

Trocar para a branch protegida e subir novamente:
```bash
git checkout feat/iot-security-solved
mise exec -- task demo
```

#### Contramedida A — Integridade e Anti-Replay no UDP (IoT Leve)
- **Como foi resolvido:**
  - Cada datagrama UDP carrega **HMAC-SHA256** (chave pré-compartilhada) + **número de sequência monotônico (`seq_num`)** + **timestamp** com janela estrita (ex.: ±5 s).
- **O que a turma vê:**
  - Pacotes alterados são rejeitados por falha no HMAC.
  - Pacotes antigos reenviados são descartados imediatamente pelo Gateway com log de alerta de segurança (`Replay detected`), mantendo a sobrecarga real de ~8000 W visível no Dashboard.

#### Contramedida B — Confidencialidade e Autenticação Mútua no gRPC e TCP (Padrão Ouro: mTLS)
- **Como foi resolvido:**
  - Criação de uma **PKI / CA local** (`ca.crt`) emitindo certificados X.509 individuais para `gateway`, `ac` e `client`.
  - Tanto o gRPC (`:50051`) quanto o TCP (`:9997`) exigem **Mutual TLS (`mTLS`)**: servidor e cliente validam mutuamente seus certificados durante o handshake TLS.
- **O que a turma vê:**
  - No Wireshark, o tráfego TCP/gRPC aparece cifrado como `TLSv1.3 Application Data` (confidencialidade restaurada).
  - Uma tentativa direta na porta `50051` sem certificado válido assinado pela CA falha ainda no **TLS Handshake** (`UNAUTHENTICATED` / `TLS Fatal Alert`), impedindo o desligamento não autorizado do AC.

---

### Ato 4 — Quadro Comparativo Final e Conclusão (2 min)

| Aspecto | `feat/iot-security` | `feat/iot-security-solved` |
| :--- | :--- | :--- |
| **Wireshark (TCP/gRPC)** | Protobuf legível em texto claro | Tráfego cifrado (`TLS`) |
| **Pacote UDP alterado** | Aceito e persistido no SQLite | Rejeitado (falha de `HMAC-SHA256`) |
| **Pacote UDP antigo (Replay)** | Aceito; mascara sobrecarga real | Rejeitado (`seq_num` / janela de timestamp) |
| **Comando gRPC direto sem credencial** | Desliga o AC com sucesso | Bloqueado no handshake `mTLS` |
| **Auditoria / Não-Repúdio** | Inexistente | Identidade por certificado X.509 + logs de segurança |

**Mensagem de fechamento:**
- Em IoT real, **não existe mecanismo único para tudo**: dispositivos restritos em streaming contínuo usam autenticação leve (HMAC + contadores anti-replay), enquanto canais de controle e gerenciamento usam **mTLS com PKI (X.509)** — combinando desempenho e defesa em profundidade.
