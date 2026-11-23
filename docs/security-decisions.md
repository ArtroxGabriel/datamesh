# Decisões e operação: laboratório de segurança

## Decisões

- `DATAMESH_SECURITY_MODE=insecure|secure` é lido na inicialização. Alterar o cenário requer
  recriar todos os serviços; não há alternância por requisição. O padrão é `insecure`.
- A descoberta multicast, anúncios e telemetria UDP usam AES-256-GCM e HMAC-SHA256 no modo seguro.
  A chave de cifragem é derivada da chave HMAC com separação de domínio; cada datagrama usa nonce
  aleatório de 96 bits. O cabeçalho, identidade, nonce e ciphertext são cobertos pelo HMAC. O payload
  é cifrado; identidade, tipo, sequência, horário do envelope e tamanho continuam visíveis.
- Esta decisão substitui a escolha anterior de HMAC sem cifragem. Todos os serviços devem ser
  recriados juntos: envelopes seguros antigos `DMS1` são rejeitados, sem fallback inseguro.
- Todas as fontes possuem a chave compartilhada do Gateway para verificar seus beacons. Logo,
  uma fonte comprometida também pode forjar beacons; este é um limite do laboratório.
- O envelope contém tipo, identidade, sequência e timestamp autenticados. O Gateway e as fontes
  persistem sequências separadamente dos dados de telemetria e rejeitam mensagens repetidas ou com
  relógio fora de ±5 segundos. O relógio dos processos precisa estar sincronizado.
- TCP Cliente–Gateway e gRPC Gateway–AC usam mTLS. Apenas o certificado `client` acessa o TCP e
  apenas `gateway` pode atuar no AC. Os certificados de laboratório expiram em sete dias.
- As chaves HMAC não oferecem não repúdio: uma entidade que conhece a chave pode gerar assinaturas.
  A CA e as chaves são locais e ignoradas pelo Git; esta configuração não é PKI de produção.
- O laboratório Compose usa uma rede interna com rota multicast explícita; `NET_ADMIN` é necessário
  somente para essa rota. O atacante recebe `NET_RAW`, a CA pública e o namespace de rede do Gateway,
  sem certificados privados nem chaves HMAC. Os scripts aceitam somente o lab Compose fixo ou loopback.
- O replay usa uma leitura normal do sensor e a anomalia térmica existente. Como a aplicação mantém
  timestamps dos pacotes e exibe séries históricas, não se presume que reenviar uma leitura antiga
  sempre oculte a anomalia: verifique o gráfico e os logs durante a apresentação.
- A nova interface visual de demonstração será uma etapa posterior; a página de rede existente e o
  dashboard continuam disponíveis.

## Preparação e execução

Na raiz do repositório:

```sh
scripts/security/setup_lab.sh
DATAMESH_SECURITY_MODE=insecure docker compose -p datamesh-security-lab -f compose.lab.yml --profile attack up -d --build --force-recreate
# Para mudar de cenário, recrie a pilha inteira:
DATAMESH_SECURITY_MODE=secure docker compose -p datamesh-security-lab -f compose.lab.yml --profile attack up -d --force-recreate
```

O dashboard fica em http://localhost:8080. O modo local também usa a mesma configuração:
`DATAMESH_SECURITY_MODE=secure mise exec -- ./scripts/run_demo.sh`. O launcher pode adicionar fontes
novas e provisiona uma chave para cada identidade. Ele limpa seu banco de telemetria temporário, mas
não o diretório `.datamesh-security-state/` que guarda sequências.

Os volumes Compose preservam as sequências entre reinícios e mudanças de cenário. Não remova nem
restaure independentemente o estado de um lado: perder ou retroceder esses contadores pode rejeitar
tráfego legítimo ou reabrir a janela de replay. Ao reprovisionar o laboratório, troque as chaves e
zere conjuntamente os estados de todas as entidades. `setup_lab.sh` preserva chaves existentes;
`generate_credentials.sh` recusa sobrescrever o diretório existente.

## Demonstrações

Use os mesmos comandos nos dois modos:

```sh
docker compose -p datamesh-security-lab -f compose.lab.yml exec attacker python scripts/attacks/lab_attack.py sniff --lab compose
docker compose -p datamesh-security-lab -f compose.lab.yml exec attacker python scripts/attacks/lab_attack.py hijack --lab compose
docker compose -p datamesh-security-lab -f compose.lab.yml exec attacker python scripts/attacks/lab_attack.py replay --lab compose
```

Para replay, acione a anomalia na janela indicada pelo script usando outro terminal:

```sh
docker compose -p datamesh-security-lab -f compose.lab.yml kill -s USR1 temperature
docker compose -p datamesh-security-lab -f compose.lab.yml logs -f gateway
```

UDP não devolve confirmação ao atacante. O script relata os envios e consulta a leitura mais recente.
No cenário inseguro, também conta ocorrências do timestamp capturado nos 100 registros retornados;
no seguro, a leitura e seu timestamp não são acessíveis ao atacante. Essa janela limitada é uma
observação, não prova de rejeição; confira também os logs do Gateway.
Na validação do laboratório, o cenário inseguro armazenou 11 cópias da leitura antiga, mas o dashboard
continuou mostrando o alerta mais recente por ordenar pelo timestamp da leitura. A captura exige Linux e
`CAP_NET_RAW`; o container de ataque já recebe essa capacidade. Fora do Compose, o script aceita
`--lab local` e usa somente loopback e as portas padrão, com as mesmas restrições de captura.

## Console de apresentação

Após `scripts/security/setup_lab.sh`, inicie a pilha completa e o atacante:

```sh
DATAMESH_SECURITY_MODE=secure docker compose -p datamesh-security-lab -f compose.lab.yml --profile attack up -d --build
```

Acesse **http://127.0.0.1:8081**. Os botões do console recriam as fontes, Gateway, cliente e
atacante no modo escolhido; o controlador permanece ativo e aguarda a descoberta das fontes antes
de liberar os cenários. O controlador possui acesso ao socket Docker e somente oferece operações
fixas do laboratório; não o exponha publicamente. O atacante não recebe esse socket ou chaves de
serviço. Um proxy com rede do host aceita conexões apenas em loopback e encaminha somente às páginas
fixas da rede interna. A porta 8080 é opcional: se já estiver ocupada, o console na 8081 continua ativo.

O replay automático captura, aciona a anomalia e reenvia; ao desmarcar **Replay automático**, a
execução aguarda o botão **Acionar anomalia e continuar**, por até 60 segundos. Um token próprio,
criado pelo setup e compartilhado apenas entre o atacante e o sensor, protege esse acionamento de
laboratório. Um pacote seguro mantido em espera pode expirar antes do replay: nesse caso o Gateway
registra a rejeição por timestamp. O timeline combina as ações do atacante com eventos reais de
segurança retornados pelo Gateway ao cliente via TCP. Os gráficos de tráfego contam quadros observados
no namespace de rede do Gateway, inclusive o próprio tráfego de acompanhamento do console.

As execuções finalizadas, suas amostras e eventos ficam no volume `lab-runs`, preservado ao trocar
modos. As listas permitem escolher uma execução de cada cenário para comparação. Se os serviços
estiverem indisponíveis, os controles de cenário permanecem desabilitados e o console informa o erro.
