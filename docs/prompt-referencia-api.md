# Prompt Para Refatorar A API Principal AutoPonto

Voce esta no repositorio da API principal AutoPonto. Nao altere o edge-node.

## Objetivo

A API AutoPonto deve sincronizar cadastros/presencas com o edge. Telemetria dos ESP32 vai direto do edge para o InterSCity via MQTT `log/{device_id}` com campo `kind`.

## Endpoints Do Edge

Manter:

```http
GET /edge/pull
POST /edge/attendance
```

Nao usar mais no edge:

```http
POST /edge/devices/status
```

Autenticacao:

```http
Authorization: NodeToken <token>
X-Node-Id: <node_id>
```

## `GET /edge/pull`

Query:

```text
node_id=<NoBorda.codigo ou uuid>
cursors=<msgpack-hex>
```

Resposta:

```json
{
  "data": {
    "salas": [],
    "dispositivos": [],
    "aulas": [],
    "alunos": [],
    "matriculas_aula": [],
    "embeddings_faciais": []
  },
  "deleted": {
    "salas": [],
    "dispositivos": [],
    "aulas": [],
    "alunos": [],
    "matriculas_aula": [],
    "embeddings_faciais": []
  },
  "cursors": {}
}
```

Campos enviados ao edge:

- `salas`: `id`, `nome`
- `dispositivos`: `id`, `sala_id`, `ativo`, `status`, `interscity_uuid`
- `aulas`: `id`, `nome`, `sala_id`, `inicio`, `fim`, `status`
- `alunos`: `id`, `matricula`, `nome`
- `matriculas_aula`: `aula_id`, `aluno_id`
- `embeddings_faciais`: `id`, `aluno_id`, `vetor`

`interscity_uuid` deve vir do recurso InterSCity associado ao `DispositivoEsp32`.

## `POST /edge/attendance`

Payload:

```json
{
  "node_id": "NO-CCET-01",
  "eventos": [
    {
      "id": "evento-local-uuid",
      "aluno_id": "aluno-uuid",
      "aula_id": "aula-uuid",
      "dispositivo_id": "9084CED6CDC0",
      "reconhecido_em": "2026-06-19T08:42:00-03:00",
      "score": 0.72
    }
  ]
}
```

Resposta:

```json
{
  "synced_ids": ["evento-local-uuid"]
}
```

Regras:

- aceitar reenvio idempotente por `id`;
- validar node, dispositivo, sala, aula e matricula do aluno;
- retornar em `synced_ids` apenas eventos aceitos.

## InterSCity

A API principal nao recebe status/logs/PIR. O edge publica diretamente:

```http
POST {INTERSCITY_API_URL}/adaptor/resources/{interscity_uuid}/data
```

Capacidades:

- `status`: vem de `log/{device_id}` com `kind=status`;
- `heap_free`, `psram_free`, `now_ms`, `rssi`, `heap_min`, `lesson`, `remaining_ms`, `next_ms`: vem de `log/{device_id}` com `kind=metrics`;
- `presenca`: vem de `log/{device_id}` com `kind=pir`.
