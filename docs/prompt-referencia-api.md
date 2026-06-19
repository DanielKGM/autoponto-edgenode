# Prompt Para Refatorar A API Principal AutoPonto

Voce esta trabalhando no repositorio da API principal AutoPonto, nao no edge-node. Refatore o contrato de sincronizacao com o edge-node para ficar coerente com o modelo local simplificado do edge.

Nao altere arquivos do repositorio `autoponto-edgenode`. Altere apenas a API principal.

## Objetivo

A API principal deve ser a fonte dos cadastros e receber presencas. Status e logs dos ESP32 nao devem mais ser enviados para a API principal pelo edge; eles serao publicados diretamente pelo edge no Resource Adaptor do InterSCity.

## Contrato Geral

Manter autenticacao por token de node:

```http
Authorization: NodeToken <token>
X-Node-Id: <node_id>
```

Manter endpoints:

```http
GET /edge/pull
POST /edge/attendance
```

Remover do contrato ativo do edge o endpoint de status:

```http
POST /edge/devices/status
```

Esse endpoint pode ser removido ou mantido apenas como legado, mas o edge-node novo nao deve depender dele.

## `GET /edge/pull`

Query params:

```text
node_id=<NoBorda.codigo ou uuid>
cursors=<msgpack-hex>
```

`cursors` e um dicionario msgpack em hexadecimal. Quando vier vazio (`80`), a API deve retornar tudo que aquele node precisa para operar offline.

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
  "cursors": {
    "salas": "cursor-opaco",
    "dispositivos": "cursor-opaco",
    "aulas": "cursor-opaco",
    "alunos": "cursor-opaco",
    "matriculas_aula": "cursor-opaco",
    "embeddings_faciais": "cursor-opaco"
  }
}
```

Os cursores devem ser opacos para o edge. A API pode usar timestamp, versao incremental ou outro marcador interno, desde que retorne apenas alteracoes posteriores no proximo pull.

## Entidades Enviadas Ao Edge

Enviar somente os campos que o edge usa.

### `salas`

```json
{
  "id": "sala-uuid",
  "nome": "LABESE"
}
```

### `dispositivos`

Cada ESP32 deve ter o UUID do recurso InterSCity quando cadastrado.

```json
{
  "id": "9084CED6CDC0",
  "sala_id": "sala-uuid",
  "ativo": true,
  "status": "idle",
  "interscity_uuid": "f3e29da0-e958-4f6a-90eb-cef7804cd28c"
}
```

Se os modelos atuais tiverem `NoBorda` e `DispositivoEsp32`, persistir o UUID InterSCity no modelo que representa o recurso real do ESP32, normalmente `DispositivoEsp32`. Se tambem existir recurso InterSCity para o proprio node, `NoBorda` pode ter campo equivalente, mas o edge-node atual so consome `dispositivos.interscity_uuid`.

### `aulas`

No edge, `aula` e a oferta agendada que acontece em uma sala durante uma janela de tempo.

```json
{
  "id": "aula-uuid",
  "nome": "AMBIENTAL",
  "sala_id": "sala-uuid",
  "inicio": "2026-06-19T08:20:00-03:00",
  "fim": "2026-06-19T10:10:00-03:00",
  "status": "ABERTA"
}
```

### `alunos`

Nao enviar `ativo`. O cache local do edge e reflexo filtrado da API principal; alunos inativos simplesmente nao devem ser enviados para aquele node.

```json
{
  "id": "aluno-uuid",
  "matricula": "20260001",
  "nome": "Daniel Silva"
}
```

### `matriculas_aula`

Relacionamento minimo para autorizar presenca na aula atual.

```json
{
  "aula_id": "aula-uuid",
  "aluno_id": "aluno-uuid"
}
```

### `embeddings_faciais`

`vetor` pode ser base64 de bytes msgpack/float32 ou lista numerica. Preferir base64 se a API ja armazena blob.

```json
{
  "id": "embedding-uuid",
  "aluno_id": "aluno-uuid",
  "vetor": "base64..."
}
```

## Delecoes

`deleted` deve usar as mesmas chaves do `data`.

Para entidades com chave simples, enviar lista de ids:

```json
{
  "deleted": {
    "alunos": ["aluno-uuid"]
  }
}
```

Para `matriculas_aula`, enviar pares:

```json
{
  "deleted": {
    "matriculas_aula": [
      {
        "aula_id": "aula-uuid",
        "aluno_id": "aluno-uuid"
      }
    ]
  }
}
```

## `POST /edge/attendance`

Payload recebido do edge:

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

Resposta esperada:

```json
{
  "synced_ids": ["evento-local-uuid"]
}
```

Requisitos:

- idempotencia por `id` do evento local;
- validar se o dispositivo pertence ao node;
- validar se a aula pertence a sala do dispositivo;
- validar se o aluno esta matriculado na aula;
- aceitar reenvio do mesmo evento sem duplicar presenca;
- retornar em `synced_ids` apenas eventos aceitos.

## InterSCity

Adicionar ou expor `interscity_uuid` no cadastro de `DispositivoEsp32`. Cada ESP32 sera um recurso InterSCity.

O edge-node publicara diretamente:

```http
POST {INTERSCITY_API_URL}/adaptor/resources/{interscity_uuid}/data
```

Capacidades esperadas:

- `status`: vem de `sts/{dispositivo_id}`;
- `rssi`, `heap_min`, `lesson`, `remainingms`, `nextms`: vem de `log/{dispositivo_id}`.

A API principal nao precisa receber status/logs dos ESP32 para esse fluxo.

## Arquivos Provaveis

Atualize os arquivos equivalentes no repositorio da API principal:

- servico de sincronizacao de borda;
- views/controllers do contrato `/edge/*`;
- serializers/schemas OpenAPI;
- models de `NoBorda`/`DispositivoEsp32`, se ainda nao tiverem `interscity_uuid`;
- testes de contrato edge.

## Testes Esperados

- Pull completo com cursores vazios retorna todas as entidades filtradas para o node.
- Pull incremental retorna apenas alteracoes posteriores aos cursores.
- Pull inclui `dispositivos.interscity_uuid`.
- Pull nao envia `alunos.ativo`.
- Deleted usa as mesmas entidades do data.
- Attendance aceita `eventos` e campos em portugues.
- Attendance e idempotente por evento.
- Endpoint antigo `/edge/devices/status` nao e necessario para o edge novo.
