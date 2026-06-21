# AutoPonto Edge Node

Computacao de borda para Raspberry Pi do AutoPonto.

O node conversa com:

- ESP32 via HTTP e MQTT local;
- API principal AutoPonto via pull/push autenticado;
- plataforma InterSCity via Resource Adaptor;
- modelos ONNX locais para deteccao e reconhecimento facial.

## Arquitetura

Containers ativos:

- `edge-app`: API HTTP, MQTT local, SQLite, sincronizacao, telemetria e persistencia de presenca.
- `face-worker`: OpenCV/ONNX, reconhecimento facial e emissao de evento positivo.
- `redis`: filas e cache quente reconstruivel.
- `mosquitto`: broker MQTT local para os ESP32.

```mermaid
flowchart LR
  ESP32[ESP32] -->|GET /context<br/>POST /frame| EdgeApp[edge-app]
  ESP32 <-->|MQTT log/cmd| Mosquitto[mosquitto]
  EdgeApp <-->|logs por kind e comando| Mosquitto
  EdgeApp <-->|filas e cache| Redis[redis]
  FaceWorker[face-worker] <-->|frames, embeddings, eventos| Redis
  EdgeApp --> SQLite[(SQLite)]
  EdgeApp <-->|pull/push presencas| AutoPonto[API AutoPonto]
  EdgeApp -->|telemetria| InterSCity[InterSCity Resource Adaptor]
```

## Modelo Local

O edge nao replica o modelo academico completo da API principal. Ele guarda so o que precisa para operar offline:

- saber qual dispositivo esta em qual sala;
- descobrir a aula atual da sala;
- validar se o aluno pertence a aula;
- reconhecer rostos por embeddings;
- registrar uma presenca valida e sincronizavel;
- armazenar o UUID InterSCity do dispositivo quando existir.

Tabelas SQLite:

- `salas`: `id`, `nome`
- `dispositivos`: `id`, `codigo`, `sala_id`, `ativo`, `interscity_uuid`
- `aulas`: `id`, `nome`, `turma_id`, `sala_id`, `inicio`, `fim`, `status`
- `alunos`: `id`, `matricula`, `nome`
- `matriculas_turma`: `id`, `turma_id`, `aluno_id`
- `embeddings_faciais`: `id`, `aluno_id`, `vetor`
- `eventos_presenca`: `id`, `aluno_id`, `aula_id`, `dispositivo_id`, `reconhecido_em`, `score`, `sync_status`
- `sync_state`: `entity`, `cursor`

`eventos_presenca` tem `UNIQUE(aluno_id, aula_id)`. Portanto, reconhecer a mesma pessoa de novo na mesma aula nao cria uma segunda presenca; o feedback usa o horario da primeira presenca.
Eventos com `sync_status=pending` nunca sao removidos por limite local. O edge poda apenas historico `synced` que ficar fora dos ultimos `MAX_EVENTOS_PRESENCA_LOCAL` registros.

```mermaid
erDiagram
  SALAS ||--o{ DISPOSITIVOS : possui
  SALAS ||--o{ AULAS : recebe
  AULAS }o--o{ MATRICULAS_TURMA : deriva_por_turma
  ALUNOS ||--o{ MATRICULAS_TURMA : participa
  ALUNOS ||--o{ EMBEDDINGS_FACIAIS : possui
  ALUNOS ||--o{ EVENTOS_PRESENCA : gera
  AULAS ||--o{ EVENTOS_PRESENCA : recebe

  SALAS {
    string id PK
    string nome
  }
  DISPOSITIVOS {
    string id PK
    string codigo UK
    string sala_id FK
    boolean ativo
    string interscity_uuid
  }
  AULAS {
    string id PK
    string nome
    string turma_id
    string sala_id FK
    datetime inicio
    datetime fim
    string status
  }
  ALUNOS {
    string id PK
    string matricula
    string nome
  }
  MATRICULAS_TURMA {
    string id PK
    string turma_id
    string aluno_id FK
  }
  EMBEDDINGS_FACIAIS {
    string id PK
    string aluno_id FK
    blob vetor
  }
  EVENTOS_PRESENCA {
    string id PK
    string aluno_id
    string aula_id
    string dispositivo_id
    datetime reconhecido_em
    float score
    string sync_status
  }
```

## Redis

Redis e fila/cache, nao fonte duravel.

- `queue:frames`: frames JPEG recebidos do ESP32.
- `queue:eventos_presenca`: eventos positivos gerados pelo `face-worker`.
- `dispositivos:por_codigo`: hash por MAC/codigo do ESP32.
- `sala:{sala_id}:aulas`: aulas ativas da sala, ordenadas por inicio.
- `face:embeddings`: hash de embeddings por `embedding_id`.
- `aula:{aula_id}:alunos`: set de alunos elegiveis para a aula.

Exemplos de estrutura:

```text
queue:frames
tipo: list
valor: msgpack({
  "dispositivoId": "dispositivo-uuid",
  "dispositivoCodigo": "ESP32-LAB101",
  "salaId": "sala-uuid",
  "aulaId": "aula-uuid",
  "receivedAt": "2026-06-18T20:10:00.000000+00:00",
  "frame": "<jpeg-bytes>"
})

queue:eventos_presenca
tipo: list
valor: msgpack({
  "eventId": "evento-local-uuid",
  "dispositivoId": "dispositivo-uuid",
  "aulaId": "aula-uuid",
  "alunoId": "aluno-uuid",
  "score": 0.72,
  "recognizedAt": "2026-06-18T20:10:03.000000+00:00"
})

face:embeddings
tipo: hash
campo: "embedding-uuid"
valor: msgpack({
  "alunoId": "aluno-uuid",
  "embedding": "<blob-msgpack-do-vetor>"
})

dispositivos:por_codigo
tipo: hash
campo: "ESP32-LAB101"
valor: msgpack({
  "dispositivo_id": "dispositivo-uuid",
  "dispositivo_codigo": "ESP32-LAB101",
  "sala_id": "sala-uuid",
  "ativo": true,
  "interscity_uuid": "resource-uuid"
})

sala:sala-uuid:aulas
tipo: string
valor: msgpack([
  {
    "id": "aula-uuid",
    "nome": "Calculo",
    "turma_id": "turma-uuid",
    "sala_id": "sala-uuid",
    "inicio": "2026-06-18T20:00:00-03:00",
    "fim": "2026-06-18T21:40:00-03:00",
    "status": "ABERTA"
  }
])

aula:aula-uuid:alunos
tipo: set
membros: "aluno-uuid-1", "aluno-uuid-2"
```

## API Local Para ESP32

### `GET /context`

Headers:

- `X-Device-Id`: MAC/codigo do ESP32
- `X-Auth`

Resposta mantida simples para o firmware:

```json
{
  "lesson_name": "AMBIENTAL",
  "msRemaining": 6500000,
  "msForNext": 0
}
```

### `POST /frame`

Headers:

- `X-Device-Id`: MAC/codigo do ESP32
- `X-Auth`
- `Content-Type: image/jpeg`

O frame so entra em `queue:frames` se existir no Redis um dispositivo ativo e uma aula atual para a sala do dispositivo.

Item interno da fila:

```json
{
  "dispositivoId": "dispositivo-uuid",
  "dispositivoCodigo": "ESP32-LAB101",
  "salaId": "sala-uuid",
  "aulaId": "aula-uuid",
  "receivedAt": "2026-06-18T12:00:00Z",
  "frame": "<bytes>"
}
```

## Fluxo De Presenca

```mermaid
sequenceDiagram
  autonumber
  participant ESP as ESP32
  participant API as edge-app
  participant R as redis
  participant W as face-worker
  participant DB as SQLite
  participant MQ as mosquitto

  ESP->>API: GET /context
  API->>R: buscar dispositivo, sala e aula atual/proxima
  API-->>ESP: lesson_name, msRemaining, msForNext
  ESP->>API: POST /frame JPEG
  API->>R: validar aula atual do dispositivo
  API->>R: RPUSH queue:frames com aulaId
  W->>R: BLPOP queue:frames
  W->>R: ler aula:{aulaId}:alunos e face:embeddings
  W->>W: detectar rosto e comparar embeddings elegiveis
  alt aluno reconhecido e elegivel
    W->>R: RPUSH queue:eventos_presenca
    API->>R: BLPOP queue:eventos_presenca
    API->>DB: INSERT OR IGNORE eventos_presenca
    API->>MQ: publish cmd/{dispositivo_codigo}
  else falha
    W-->>W: log sem MQTT
  end
```

Payload MQTT positivo:

```json
{
  "auth": true,
  "msg": "Daniel Silva - registrado 08:42"
}
```

Nao ha MQTT negativo. Falha de decode, sem rosto, aluno desconhecido ou aluno fora da aula atual apenas gera log.

## Sincronizacao Com A API AutoPonto

O edge sincroniza dados replicados e presencas com a API principal. Horarios padrao UFMA nao sao buscados na API: o agendamento usa somente `data/horarios_ufma_fallback.json`.
Ao registrar uma presenca local, o edge tenta enviar esse evento imediatamente. Se o envio falhar, o evento permanece `pending` e volta a ser enviado pelos ciclos agendados de sincronizacao.

Autenticacao:

```http
Authorization: NodeToken <AUTOPONTO_API_TOKEN>
X-Node-Id: <NODE_ID>
```

### Pull

Endpoint:

```http
GET /edge/pull/?node_id=<NODE_ID>&cursors=<msgpack-hex>
```

Payload esperado:

```json
{
  "data": {
    "salas": [],
    "dispositivos": [],
    "aulas": [],
    "alunos": [],
    "matriculas_turma": [],
    "embeddings_faciais": []
  },
  "deleted": {
    "salas": [],
    "dispositivos": [],
    "aulas": [],
    "alunos": [],
    "matriculas_turma": [],
    "embeddings_faciais": []
  },
  "cursors": {
    "aulas": "2026-06-18T12:00:00Z"
  }
}
```

Cursores:

- `cursors` sao marcadores incrementais por entidade, salvos em `sync_state`.
- Na primeira sincronizacao ou quando faltar algum cursor, o edge envia `full=true` e substitui o cache replicado local.
- Depois de aplicar o pull com sucesso, o edge salva os cursores retornados pelo backend.
- No proximo ciclo, o edge envia esses cursores para receber apenas alteracoes posteriores.
- Horarios padrao UFMA nao fazem parte de `data`, `deleted` nem `cursors`.

Campos por recurso:

- `salas`: `id`, `nome`
- `dispositivos`: `id`, `codigo`, `sala_id`, `ativo`, `interscity_uuid`
- `aulas`: `id`, `nome`, `turma_id`, `sala_id`, `inicio`, `fim`, `status`
- `alunos`: `id`, `matricula`, `nome`
- `matriculas_turma`: `id`, `turma_id`, `aluno_id`
- `embeddings_faciais`: `id`, `aluno_id`, `vetor`

### Push De Presencas

Endpoint:

```http
POST /edge/attendance/
```

Payload:

```json
{
  "node_id": "NO-CCET-01",
  "eventos": [
    {
      "id": "evento-local-uuid",
      "aluno_id": "aluno-uuid",
      "aula_id": "aula-uuid",
      "dispositivo_id": "dispositivo-uuid",
      "reconhecido_em": "2026-06-18T11:42:00Z",
      "score": 0.72
    }
  ]
}
```

Resposta esperada:

```json
{
  "synced_ids": ["evento-local-uuid"]
}
```

### Sync Manual

O comando manual para um ciclo incremental e:

```bash
./scripts/sincronizacao-incremental-edge.sh
```

O comando manual para um pull completo e:

```bash
./scripts/sincronizacao-completa-edge.sh
```

## Telemetria InterSCity

Status e logs dos ESP32 nao sao enviados para a API AutoPonto. O edge publica diretamente no Resource Adaptor do InterSCity quando:

- `INTERSCITY_API_URL` e `RESOURCE_ADAPTOR_PATH` estao configurados;
- o cache Redis do dispositivo por MAC/codigo tem `interscity_uuid`;
- o Resource Adaptor aceita o recurso/capacidade.

Variaveis:

```env
INTERSCITY_API_URL=https://cidadesinteligentes.lsdi.ufma.br/interscity_lh
RESOURCE_ADAPTOR_PATH=/adaptor/resources
INTERSCITY_QUEUE_MAX=1000
INTERSCITY_WORKERS=1
INTERSCITY_TIMEOUT_SECONDS=5
```

Endpoint usado:

```http
POST {INTERSCITY_API_URL}{RESOURCE_ADAPTOR_PATH}/{interscity_uuid}/data
```

Todos os registros do firmware chegam por `log/{dispositivo_codigo}` em JSON com o campo `kind`. `dispositivo_codigo` e o MAC/codigo usado pelo ESP32.

`kind=status` vira a capacidade `status`:

```json
{
  "kind": "status",
  "status": "working"
}
```

No firmware, mensagens `kind=status` devem usar `retain=true`. O Last Will tambem deve usar o mesmo topico `log/{dispositivo_codigo}`, payload `{"kind":"status","status":"offline"}` e `retain=true`. Mensagens `kind=metrics` e `kind=pir` nao devem usar retain.

Payload InterSCity gerado:

```json
{
  "data": {
    "status": [
      {
        "value": "working",
        "timestamp": "2026-06-19T00:21:43.000"
      }
    ]
  }
}
```

`kind=metrics` e publicado a cada minuto pelo firmware e vira somente estas capacidades:

- `heap_free`
- `psram_free`
- `now_ms`
- `rssi`
- `heap_min`
- `lesson`
- `remaining_ms`
- `next_ms`

`state` nao e publicado em logs porque representa status. O firmware tambem deve remover `state` do payload de log.

`kind=pir` e publicado quando o sensor PIR detectar presenca e vira a capacidade `presenca`. Esse evento nao vem da funcao periodica de metricas.

Exemplo de `kind=metrics`:

```json
{
  "kind": "metrics",
  "heap_free": 120000,
  "psram_free": 3000000,
  "now_ms": 123456,
  "rssi": -62,
  "heap_min": 123456,
  "lesson": "AMBIENTAL",
  "remaining_ms": 60000,
  "next_ms": 0
}
```

Payload InterSCity gerado:

```json
{
  "data": {
    "heap_free": [
      {
        "value": 120000,
        "timestamp": "2026-06-19T00:22:43.000"
      }
    ],
    "psram_free": [
      {
        "value": 3000000,
        "timestamp": "2026-06-19T00:22:43.000"
      }
    ],
    "now_ms": [
      {
        "value": 123456,
        "timestamp": "2026-06-19T00:22:43.000"
      }
    ],
    "rssi": [
      {
        "value": -62,
        "timestamp": "2026-06-19T00:22:43.000"
      }
    ],
    "heap_min": [
      {
        "value": 123456,
        "timestamp": "2026-06-19T00:22:43.000"
      }
    ],
    "lesson": [
      {
        "value": "AMBIENTAL",
        "timestamp": "2026-06-19T00:22:43.000"
      }
    ],
    "remaining_ms": [
      {
        "value": 60000,
        "timestamp": "2026-06-19T00:22:43.000"
      }
    ],
    "next_ms": [
      {
        "value": 0,
        "timestamp": "2026-06-19T00:22:43.000"
      }
    ]
  }
}
```

Exemplo de `kind=pir`:

```json
{
  "kind": "pir",
  "presenca": true
}
```

Payload InterSCity gerado:

```json
{
  "data": {
    "presenca": [
      {
        "value": true,
        "timestamp": "2026-06-19T00:23:10.000"
      }
    ]
  }
}
```

O listener MQTT apenas enfileira a publicacao. Workers em background fazem o POST para o InterSCity. Se a fila estiver cheia ou o InterSCity estiver indisponivel, o edge registra warning e continua operando localmente.
Para testes sem recursos/capacidades cadastrados, deixe `INTERSCITY_API_URL` vazio ou nao envie `interscity_uuid` no pull dos dispositivos.

```mermaid
sequenceDiagram
  autonumber
  participant ESP as ESP32
  participant MQ as mosquitto
  participant API as edge-app
  participant R as Redis
  participant IS as InterSCity

  ESP->>MQ: publish log/{dispositivo_codigo} kind=status retain
  MQ->>API: status
  API->>R: enfileirar publicacao
  API->>R: worker resolve interscity_uuid
  API->>IS: POST capacidade status
  ESP->>MQ: publish log/{dispositivo_codigo} kind=metrics a cada 1 min
  MQ->>API: metricas periodicas
  API->>R: enfileirar publicacao
  API->>R: worker resolve interscity_uuid
  API->>IS: POST capacidades de log
  ESP->>MQ: publish log/{dispositivo_codigo} kind=pir ao detectar PIR
  MQ->>API: presenca
  API->>R: enfileirar publicacao
  API->>R: worker resolve interscity_uuid
  API->>IS: POST capacidade presenca
```

## Reset De Dados Local

Use quando mudar o schema local ou quiser recriar o cache SQLite:

```bash
docker compose down -v --remove-orphans
rm -f data/db/db.sql data/db/db.sql-wal data/db/db.sql-shm
docker compose up -d --build
```

Depois do reset, os dados locais voltam pelo proximo pull completo da API principal.

## Setup

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo apt install docker-compose-plugin -y
sudo sysctl vm.overcommit_memory=1
```

```bash
cp .env.example .env
chmod +x scripts/init-mosquitto-password.sh
./scripts/init-mosquitto-password.sh
docker compose up -d --build
docker compose ps
```

### Agendamento Do Sync

O `edge-app` nao tem loop interno de sincronizacao. Use a crontab do Linux para executar sync completa no startup/virada de dia e sync incremental antes dos inicios dos horarios padrao UFMA.

Revise as tarefas geradas sem alterar a crontab:

```bash
./scripts/atualizar-agendamentos-sincronizacao-edge.sh --dry-run
```

Grave ou atualize o bloco de tarefas do AutoPonto Edge:

```bash
./scripts/atualizar-agendamentos-sincronizacao-edge.sh
```

O script le `data/horarios_ufma_fallback.json` e recria somente o bloco entre `# AUTOPONTO EDGE SYNC BEGIN` e `# AUTOPONTO EDGE SYNC END`. Ele nao busca horarios padrao UFMA na API.

## Modelos ONNX

```bash
wget https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx -O ./data/models/face_detection_yunet.onnx
wget https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx -O ./data/models/face_recognition_sface.onnx
```

## Prompts De Referencia

As alteracoes esperadas na API principal e no firmware ficam em documentos separados, em formato de prompt para LLM:

- [docs/prompt-referencia-api.md](docs/prompt-referencia-api.md)
- [docs/prompt-referencia-firmware.md](docs/prompt-referencia-firmware.md)

Os diretorios `referencia-api/` e `referencia-firmware/` sao apenas referencia local e nao devem ser editados por este projeto.
