# Guia Rápido: Testes e Laboratório Docker (`DATAMESH_SECURITY_MODE`)

> **Nota:** Após o merge no GitHub, execute `git pull` localmente para sincronizar `compose.lab.yml`, `scripts/security/` e `docs/security-decisions.md`.

---

## 1. Testes Automatizados e Checagens

Na raiz do repositório:

```bash
# Testes, checagem de tipos e lint (Python)
uv run pytest
uv run ty check
uv run ruff check .

# Testes e análise estática (Go - PDU)
mise exec -- go test ./sources/pdu/...
mise exec -- go vet ./sources/pdu/...
```

---

## 2. Laboratório Docker Compose (Cenário Inseguro vs. Seguro)

### Passo 1 — Provisionar credenciais locais (uma única vez)

Gera a CA local, certificados X.509, chaves HMAC e o token do laboratório em `.datamesh-security/`:

```bash
scripts/security/setup_lab.sh
```

### Passo 2 — Subir ou alternar o cenário

`DATAMESH_SECURITY_MODE` é lido na inicialização dos processos. Ao alternar entre `insecure` e `secure`, **recrie toda a pilha**:

```bash
# Cenário 1: Inseguro (padrão)
DATAMESH_SECURITY_MODE=insecure docker compose -p datamesh-security-lab -f compose.lab.yml --profile attack up -d --build --force-recreate

# Cenário 2: Seguro (AES-256-GCM + HMAC-SHA256 no UDP, mTLS no TCP/gRPC)
DATAMESH_SECURITY_MODE=secure docker compose -p datamesh-security-lab -f compose.lab.yml --profile attack up -d --build --force-recreate
```

### Passo 3 — Executar os ataques e validações

- **Via Console Web:** acesse `http://127.0.0.1:8081` para alternar cenários e disparar os ataques visualmente.
- **Via CLI (container `attacker`):**

```bash
docker compose -p datamesh-security-lab -f compose.lab.yml exec attacker python scripts/attacks/lab_attack.py sniff --lab compose
docker compose -p datamesh-security-lab -f compose.lab.yml exec attacker python scripts/attacks/lab_attack.py hijack --lab compose
docker compose -p datamesh-security-lab -f compose.lab.yml exec attacker python scripts/attacks/lab_attack.py replay --lab compose
```

Durante a janela solicitada pelo ataque de `replay`, dispare a anomalia térmica em outro terminal:

```bash
docker compose -p datamesh-security-lab -f compose.lab.yml kill -s USR1 temperature
```

### Cuidados Operacionais
- **Sincronização de estado:** não apague nem restaure apenas um volume de sequência (`gateway-state`, `ac-state`, `temperature-state`, `pdu-state`) isoladamente; perder ou retroceder contadores faz o Gateway rejeitar pacotes legítimos como replay.
- **Validade dos certificados:** os certificados gerados pelo `setup_lab.sh` expiram em **7 dias**.
