# AutoPonto Edge Node

Computacao de borda para Raspberry Pi do sistema AutoPonto.

O node conversa com:

- dispositivos ESP32 via HTTP e MQTT local;
- servidor principal via sincronizacao por polling;
- modelos ONNX locais para deteccao/reconhecimento facial.

## Arquitetura atual

Containers ativos:

- `edge-app`: API HTTP, listener MQTT de status, SQLite local, sync e persistencia de presencas.
- `face-worker`: processamento OpenCV/ONNX, reconhecimento facial e feedback MQTT positivo.
- `redis`: fila de frames, fila de presencas e cache quente de embeddings/elegibilidade.
- `mosquitto`: broker MQTT local para os ESP32.

O antigo `edge-api` e o antigo `mqtt-listener` foram fundidos no `edge-app`.

```mermaid
flowchart LR
  ESP32[ESP32] -->|HTTP /context e /frame| EdgeApp[edge-app]
  ESP32 <-->|MQTT sts/cmd| Mosquitto[mosquitto]
  EdgeApp <-->|status MQTT| Mosquitto
  EdgeApp <-->|filas e cache| Redis[redis]
  FaceWorker[face-worker] <-->|frames, embeddings, presencas| Redis
  FaceWorker -->|MQTT cmd positivo| Mosquitto
  EdgeApp <-->|polling sync| MainAPI[servidor principal]
  EdgeApp --> SQLite[(SQLite local)]
```

## Modelo local

`attendance_event` e uma presenca local valida: ela so existe quando um aluno foi reconhecido, esta matriculado na `lesson` atual do dispositivo e precisa ser sincronizado com o servidor principal.

`lesson` representa a cadeira/aula ofertada no edge, por exemplo `Algoritmos` ou `Matematica Aplicada`. Ela acontece em um `locale`, como `Laboratorio A` ou `Sala 208`, dentro de uma janela `starts_at`/`ends_at`.

`enrollments` e a tabela relacional entre estudantes e lessons. Ela responde a pergunta: este estudante pertence a esta aula atual?

SQLite e a fonte duravel local:

- `locales`: `id`, `name`
- `devices`: `id`, `locale_id`, `active`
- `lessons`: `id`, `name`, `locale_id`, `starts_at`, `ends_at`
- `students`: `id`, `registration`, `name`, `active`
- `enrollments`: `lesson_id`, `student_id`
- `face_embeddings`: `id`, `student_id`, `embedding`
- `attendance_events`: `id`, `student_id`, `lesson_id`, `device_id`, `recognized_at`, `score`, `sync_status`
- `sync_state`: `entity`, `cursor`

Redis e cache/fila reconstruivel:

- `queue:frames`
- `queue:attendance_events`
- `face:embeddings`
- `lesson:{lesson_id}:students`
- `device:{device_id}:status`
- `devices:last_seen`

```mermaid
erDiagram
  LOCALES ||--o{ DEVICES : has
  LOCALES ||--o{ LESSONS : hosts
  LESSONS ||--o{ ENROLLMENTS : allows
  STUDENTS ||--o{ ENROLLMENTS : attends
  STUDENTS ||--o{ FACE_EMBEDDINGS : has
  STUDENTS ||--o{ ATTENDANCE_EVENTS : generates
  LESSONS ||--o{ ATTENDANCE_EVENTS : receives
  DEVICES ||--o{ ATTENDANCE_EVENTS : records

  LOCALES {
    string id PK
    string name
  }
  DEVICES {
    string id PK
    string locale_id FK
    boolean active
  }
  LESSONS {
    string id PK
    string name
    string locale_id FK
    datetime starts_at
    datetime ends_at
  }
  STUDENTS {
    string id PK
    string registration
    string name
    boolean active
  }
  ENROLLMENTS {
    string lesson_id PK,FK
    string student_id PK,FK
  }
  FACE_EMBEDDINGS {
    string id PK
    string student_id FK
    blob embedding
  }
  ATTENDANCE_EVENTS {
    string id PK
    string student_id
    string lesson_id
    string device_id
    datetime recognized_at
    float score
    string sync_status
  }
```

## Fluxo de presenca

1. ESP32 chama `GET /context` com `X-Device-Id` e `X-Auth`.
2. `edge-app` consulta SQLite e retorna aula atual/proxima para o local do dispositivo.
3. ESP32 envia `POST /frame` com `Content-Type: image/jpeg`.
4. `edge-app` so enfileira o frame se houver `lesson` atual para o dispositivo.
5. `face-worker` consome `queue:frames`.
6. O reconhecimento compara apenas embeddings de alunos matriculados naquela `lesson`.
7. Em sucesso autorizado:
   - publica `cmd/{device_id}` com `auth: true` e `studentId`;
   - enfileira evento em `queue:attendance_events`;
   - `edge-app` persiste em `attendance_events` com `sync_status = pending`.
8. Em falha, sem rosto, aluno desconhecido ou aluno fora da lesson:
   - nao publica MQTT;
   - apenas registra log.

```mermaid
sequenceDiagram
  autonumber
  participant ESP as ESP32
  participant API as edge-app
  participant R as redis
  participant W as face-worker
  participant MQ as mosquitto
  participant DB as SQLite

  ESP->>API: GET /context
  API->>DB: buscar device, locale e lesson atual/proxima
  API-->>ESP: lesson_name, msRemaining, msForNext
  ESP->>API: POST /frame JPEG
  API->>DB: validar lesson atual do device
  API->>R: RPUSH queue:frames com lessonId
  W->>R: BLPOP queue:frames
  W->>R: ler lesson:{lessonId}:students e face:embeddings
  W->>W: detectar rosto e comparar embeddings elegiveis
  alt aluno reconhecido e matriculado
    W->>MQ: publish cmd/{device_id} auth=true
    W->>R: RPUSH queue:attendance_events
    API->>R: BLPOP queue:attendance_events
    API->>DB: INSERT attendance_events pending
  else falha ou aluno nao elegivel
    W-->>W: log sem MQTT
  end
```

## Sincronizacao

O servidor principal ainda nao existe, entao o contrato abaixo define a expectativa do edge.

Se `MAIN_API_URL` estiver vazio, o node opera offline e nao tenta sincronizar. Quando configurado, `edge-app` roda um loop periodico:

1. Le os cursores locais em `sync_state`.
2. Chama `GET /edge/pull` com `node_id` e cursores.
3. Recebe cadastros alterados e remocoes.
4. Aplica tudo no SQLite dentro de uma transacao.
5. Reconstroi o cache Redis usado pelo `face-worker`.
6. Busca `attendance_events` com `sync_status = pending`.
7. Envia esses eventos para `POST /edge/attendance`.
8. Marca como `synced` apenas os IDs confirmados pelo servidor.
9. Se qualquer etapa falhar, mantem dados locais e tenta novamente no proximo ciclo.

Payload esperado de pull:

```json
{
  "data": {
    "locales": [],
    "devices": [],
    "lessons": [],
    "students": [],
    "enrollments": [],
    "face_embeddings": []
  },
  "deleted": {
    "locales": [],
    "devices": [],
    "lessons": [],
    "students": [],
    "enrollments": [],
    "face_embeddings": []
  },
  "cursors": {
    "students": "cursor-value"
  }
}
```

```mermaid
flowchart TD
  Timer[intervalo de sync] --> Cursors[ler sync_state]
  Cursors --> Pull[GET /edge/pull]
  Pull --> Tx[transacao SQLite]
  Tx --> Cache[reconstruir Redis cache]
  Cache --> Pending[buscar attendance_events pending]
  Pending --> Push[POST /edge/attendance]
  Push --> Confirm{servidor confirmou?}
  Confirm -->|sim| Synced[marcar sync_status=synced]
  Confirm -->|nao| Retry[manter pending]
  Retry --> Timer
  Synced --> Timer
```

Variaveis:

- `NODE_ID`
- `MAIN_API_URL`
- `MAIN_API_TOKEN`
- `SYNC_INTERVAL_SECONDS`

Endpoints esperados no servidor principal:

- `GET /edge/pull`: retorna cadastros, horarios, alunos, matriculas, embeddings, remocoes e cursores.
- `POST /edge/attendance`: recebe presencas pendentes e retorna ids sincronizados.

## Setup

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo apt install docker-compose-plugin -y
sudo sysctl vm.overcommit_memory=1
```

Firewall:

```bash
sudo apt install ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 1883/tcp
sudo ufw allow 22/tcp
sudo ufw allow 8080/tcp
```

Env:

```bash
cp .env.example .env
chmod +x scripts/init-mosquitto-password.sh
./scripts/init-mosquitto-password.sh
```

Subir:

```bash
docker compose up -d --build
docker compose ps
```

## Modelos ONNX

Modelos usados do OpenCV Zoo:

```bash
wget https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx -O ./data/models/face_detection_yunet.onnx
wget https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx -O ./data/models/face_recognition_sface.onnx
```

## systemd

```bash
sudo nano /etc/systemd/system/edge-node.service
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable edge-node
sudo systemctl start edge-node
sudo systemctl status edge-node
```

## mDNS

```bash
sudo hostnamectl set-hostname autopontonode
sudo apt update
sudo apt install avahi-daemon
sudo systemctl enable avahi-daemon
sudo systemctl start avahi-daemon
```
