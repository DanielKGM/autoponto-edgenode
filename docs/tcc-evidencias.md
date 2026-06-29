# Evidencias Para O TCC

Este documento concentra os artefatos para Metodologia e Analise dos
Resultados do EdgeNode.

## Arquivos Gerados

| Arquivo | Conteudo |
| --- | --- |
| `/data/logs/tcc/metricas_amostras.csv` | Amostras append-only das metricas de HTTP, fila, reconhecimento, sync e InterSCity. |
| `/data/logs/tcc/metricas_resumo.txt` | Resumo recalculado com quantidade, media e desvio padrao amostral quando ha valor numerico. |
| `/data/logs/metricas_avg_us.txt` | Media ponderada e desvio padrao ponderado das metricas `avg_us` do ESP32 selecionado. |
| `/data/logs/metricas_avg_us_amostras.csv` | Amostras append-only de cada captura `avg_us` recebida do ESP32 selecionado. |

## Matriz De Metricas

| Metrica | Unidade | Servico de origem | Como sera usada no TCC |
| --- | --- | --- | --- |
| `http_context_ms` | ms | `edge-app` | Medir latencia e quantidade de consultas `GET /context` feitas pelo ESP32. |
| `http_frame_ms` | ms | `edge-app` | Medir latencia e quantidade de envios `POST /frame` ate o enfileiramento. |
| `frame_espera_processamento_ms` | ms | `face-worker` | Avaliar atraso entre recebimento do frame e inicio do processamento. |
| `deteccao_facial_ms` | ms | `face-worker` | Isolar o custo da etapa de deteccao facial com YuNet. |
| `embedding_extracao_ms` | ms | `face-worker` | Isolar o custo de geracao do embedding facial com SFace. |
| `embedding_comparacao_ms` | ms | `face-worker` | Medir o custo de carregar/comparar embeddings elegiveis da aula. |
| `reconhecimento_total_ms` | ms | `face-worker` | Medir o tempo fim-a-fim do reconhecimento por frame processado. |
| `snapshot_pull_ms` | ms | `edge-app` | Medir o tempo do pull do snapshot no servidor principal. |
| `sync_falha` | evento | `edge-app` | Contabilizar falhas de pull, aplicacao de snapshot, push de presencas e fetch MQTT pos-sync. |
| `interscity_publicacao_ms` | ms | `edge-app` | Medir latencia e taxa de sucesso/falha das publicacoes no InterSCity. |
| `interscity_publicacao` | evento | `edge-app` | Contabilizar descarte por fila local cheia. |
| `avg_us.loop` | microssegundos | ESP32 via `edge-app` | Avaliar custo medio do loop principal do firmware durante o teste. |
| `avg_us.mqtt` | microssegundos | ESP32 via `edge-app` | Avaliar custo medio das rotinas MQTT no firmware. |
| `avg_us.network` | microssegundos | ESP32 via `edge-app` | Avaliar custo medio das rotinas de rede no firmware. |
| `avg_us.camera` | microssegundos | ESP32 via `edge-app` | Avaliar custo medio de captura/processamento local de camera. |
| `avg_us.display` | microssegundos | ESP32 via `edge-app` | Avaliar custo medio de atualizacao do display. |

Notas:

- O resumo geral usa desvio padrao amostral das amostras numericas registradas.
- As metricas `avg_us` usam media ponderada por `avg_count`.
- O desvio padrao de `avg_us` e ponderado entre capturas recebidas; ele nao
  representa variancia interna de cada lote do firmware, porque o ESP32 envia
  media e contagem, nao a variancia bruta.

## Arquitetura Do EdgeNode

```mermaid
flowchart LR
  ESP32[ESP32] -->|GET /context<br/>POST /frame| EdgeApp[edge-app]
  ESP32 <-->|log/{codigo}<br/>cmd/{codigo}| Mosquitto[mosquitto]
  Mosquitto -->|logs por kind| EdgeApp
  EdgeApp <-->|snapshot, filas, presencas| Redis[redis]
  FaceWorker[face-worker] <-->|frames, embeddings, eventos| Redis
  EdgeApp <-->|pull snapshot<br/>push presencas| AutoPonto[API AutoPonto]
  EdgeApp -->|telemetria| InterSCity[Resource Adaptor InterSCity]
```

## Fluxo De Reconhecimento

```mermaid
sequenceDiagram
  autonumber
  participant ESP as ESP32
  participant API as edge-app
  participant R as Redis
  participant W as face-worker

  ESP->>API: GET /context
  API->>R: consulta snapshot, dispositivo e aula
  API-->>ESP: aula atual/proxima
  ESP->>API: POST /frame JPEG
  API->>R: RPUSH queue:frames
  W->>R: BLPOP queue:frames
  W->>W: detecta rosto
  W->>W: extrai embedding
  W->>R: carrega embeddings elegiveis
  W->>W: compara score
  alt reconhecido
    W->>R: RPUSH queue:eventos_presenca
  else nao reconhecido
    W-->>W: registra falha local
  end
```

## Fluxo De Sincronizacao

```mermaid
sequenceDiagram
  autonumber
  participant Cron as cron/script
  participant API as edge-app sync
  participant BE as API AutoPonto
  participant R as Redis
  participant MQTT as mosquitto

  Cron->>API: python -m app.sync
  API->>BE: GET /edge/pull/?node_id
  BE-->>API: snapshot do dia
  API->>API: descriptografa embeddings
  API->>R: substitui snapshot atomico
  API->>MQTT: publish cmd/{codigo} {"fetch": true}
  API->>R: le presencas pendentes
  API->>BE: POST /edge/attendance/
  BE-->>API: synced_ids
  API->>R: marca presencas sincronizadas
```

## Fluxo MQTT De Feedback

```mermaid
sequenceDiagram
  autonumber
  participant W as face-worker
  participant R as Redis
  participant API as edge-app
  participant MQTT as mosquitto
  participant ESP as ESP32

  W->>R: queue:eventos_presenca
  API->>R: BLPOP queue:eventos_presenca
  API->>R: salva presenca idempotente
  API->>MQTT: publish cmd/{dispositivoCodigo}
  MQTT-->>ESP: {"auth": true, "msg": "Nome (HH:MM)"}
```

## Fluxo De Telemetria InterSCity

```mermaid
sequenceDiagram
  autonumber
  participant ESP as ESP32
  participant MQTT as mosquitto
  participant API as edge-app
  participant R as Redis
  participant IC as InterSCity

  ESP->>MQTT: publish log/{codigo} kind=status|metrics|pir
  MQTT-->>API: log/{codigo}
  API->>R: consulta interscity_uuid do dispositivo
  API->>API: filtra capacidades
  API->>IC: POST /adaptor/resources/{uuid}/data
  alt sucesso
    IC-->>API: 2xx
  else falha
    API-->>API: registra falha e mantem operacao local
  end
```
