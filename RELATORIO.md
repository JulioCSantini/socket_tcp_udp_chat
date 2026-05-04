# Relatório — Chat com sockets TCP e UDP

**Disciplina:** Redes de computadores  
**Projeto:** `socket_tcp_udp_chat` (servidor/cliente TCP e UDP)

---

## 1. Descrição do funcionamento

### 1.1 Visão geral

O sistema implementa um **chat em modo cliente–servidor**. O **servidor** centraliza o estado (quem está online, salas, encaminhamento de mensagens) e os **clientes** enviam e recebem **linhas de texto** em um protocolo simples baseado em comandos (por exemplo `IDENT`, `LIST`, `PRIV`). A comunicação ocorre por **sockets**: **TCP** (fluxo confiável, orientado à conexão) ou **UDP** (datagramas, sem conexão persistente no protocolo).

### 1.2 Protocolo (linhas de texto)

- Após abrir a comunicação, o cliente deve enviar **`IDENT <nome>`** para se registrar. O nome segue regras de validação (tamanho e caracteres permitidos). O servidor responde com **`OK`** ou **`ERR`**.
- Comandos principais (após identificação): **`LIST`** (usuários conectados ao servidor), **`WHO`** (usuários na sala atual), **`ROOMS`** (salas e quantidade de usuários), **`JOINROOM <sala>`** (trocar de sala), **`PRIV <usuário> <mensagem>`** (mensagem privada).
- Qualquer outra linha é tratada como **mensagem pública**, enviada apenas aos clientes que estão na **mesma sala** que o remetente.
- No **UDP**, o cliente envia periodicamente **`PING`** para renovar a “sessão” no servidor (evitar remoção por inatividade).

### 1.3 Servidor TCP

O servidor **aceita conexões** (`accept`), cria **uma thread por cliente** e lê dados em laço, acumulando bytes em buffer até formar linas completas (delimitador `\n`). O encerramento do socket ou erro encerra a thread e remove o cliente das estruturas internas. Há **mutex** (`threading.Lock`) para acesso seguro às estruturas compartilhadas (mapa de usuários, salas).

### 1.4 Servidor UDP

Não há conexão TCP: cada mensagem chega como um **datagrama** com endereço de origem `(IP, porta)`. O servidor associa esse endereço a um **nome de usuário** após o `IDENT` e mantém **último instante de atividade** para cada origem. Uma **thread de limpeza** remove periodicamente clientes **sem tráfego** por mais tempo que o limite configurado (sessão expirada). O encaminhamento de mensagens públicas e de sala usa o mesmo critério do TCP, mas o envio é feito com **`sendto`** para cada destino.

### 1.5 Salas de conversa (funcionalidade extra)

Todo usuário identificado entra na sala padrão **`geral`**. O comando **`JOINROOM`** altera a sala lógica do cliente. O chat público é **filtrado por sala** no servidor (roteamento na camada de aplicação). Eventos como entrada/saída de sala são notificados com mensagens do tipo **`ROOMENTER`** / **`ROOMLEAVE`**.

### 1.6 Logs

Em ambas as implementações o servidor registra eventos relevantes (conexões, identificação, erros, mensagens resumidas, trocas de sala, etc.) em arquivo **`server.log`** na respectiva pasta (`tcp/` ou `udp/`), além de exibir parte das informações no console.

---

## 2. Funcionalidades implementadas

| Funcionalidade | Descrição |
|-----------------|-----------|
| **Identificação ao conectar** | Obrigatório enviar `IDENT <nome>`; validação de nome e unicidade no servidor. |
| **Lista de usuários conectados** | Comando `LIST`; resposta `USERS` com os nomes registrados no servidor. |
| **Mensagens privadas** | Comando `PRIV <destinatário> <texto>`; entrega apenas ao destinatário; confirmação ao remetente. |
| **Registro de logs no servidor** | Arquivo `server.log` + console, com carimbo de data/hora e nível. |
| **Salas de conversa (extra)** | Sala padrão `geral`; `JOINROOM`, `ROOMS`, `WHO`; chat público restrito à sala; notificações de sala. |
| **UDP — manutenção de sessão** | `PING` / `PONG` e timeout de inatividade para simular “presença” sem conexão TCP. |

Os clientes exibem as respostas do servidor de forma legível (incluindo prefixo de sala nas mensagens públicas quando o formato `CHAT <sala> <autor> <texto>` é usado).

---

## 3. Diferenças observadas entre TCP e UDP

### 3.1 Modelo de transporte

| Aspecto | TCP | UDP |
|---------|-----|-----|
| **Conexão** | Conexão explícita (`connect` / `accept`); estado “conectado” é natural do protocolo. | Sem conexão no nível de transporte; cada pacote é independente. |
| **Confiabilidade e ordem** | Entrega ordenada e com retransmissão; fluxo contínuo de bytes. | Não garante ordem nem entrega; datagramas podem se perder ou duplicar (não tratado neste trabalho além do que o app exige). |
| **Limite de mensagem** | Stream: o app monta **linhas** a partir de vários `recv`. | Cada `recvfrom` traz **um datagrama** (tamanho limitado, ex.: buffer 4096 bytes); mensagens muito longas podem ser truncadas pelo tamanho do buffer. |

### 3.2 Implementação no servidor

- **TCP:** uma **thread por cliente**, leitura bloqueante por socket, remoção do cliente ao **fechar a conexão** (fim do stream ou erro).
- **UDP:** um **laço único** de `recvfrom` + **mapeamento (IP, porta) → usuário**; **timeout** para remover quem para de enviar pacotes; thread auxiliar de **limpeza periódica**; uso intensivo de **`sendto`** para cada destino.

### 3.3 Semântica de “usuário online”

- **TCP:** “online” coincide com **socket aberto** após `IDENT`.
- **UDP:** “online” é **inferido** pela última atividade; sem pacotes dentro do intervalo, o servidor considera a sessão encerrada e remove o usuário (com notificações compatíveis com o restante do protocolo).

### 3.4 Complexidade percebida

- **TCP:** mais simples para chat contínuo e controle de desconexão (o próprio fechamento do TCP sinaliza saída).
- **UDP:** exige **lógica adicional** no aplicativo (sessão por endereço, heartbeat, expiração) para aproximar o comportamento de presença e lista de usuários de forma coerente com a natureza não orientada à conexão do UDP.

### 3.5 Uso típico na disciplina

- **TCP** costuma ser preferido quando se deseja **canal confiável** e contínuo (ex.: texto, controle de sessão).
- **UDP** ilustra bem **baixa latência** e **sem estado de conexão**, mas o **aplicativo** assume parte da responsabilidade que o TCP já oferece (presença, consistência opcional, tamanho de mensagem).

---

## 4. Conclusão (opcional para o grupo)

As duas versões expõem as **mesmas funcionalidades de produto** (identificação, lista, privado, salas, logs), mas o **UDP** evidencia trade-offs da camada de transporte: menos estrutura nativa de sessão, mais responsabilidade no servidor para **manter estado** e **limpar clientes inativos**. O **TCP** alinha-se naturalmente a um chat com conexão persistente e delimitação de mensagens no stream.

---

*Documento gerado com base no código do repositório `socket_tcp_udp_chat`. Ajustem nomes dos integrantes, turma e data na versão final entregue ao professor.*
