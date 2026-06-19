# Prompt Para Refatorar O Firmware ESP32 AutoPonto

Voce esta no repositorio do firmware ESP32. Nao altere o edge-node.

## Objetivo

Centralizar telemetria no topico `log/{device_id}` usando o campo JSON `kind`.

Manter `cmd/{device_id}` para comandos/feedback do edge.

## `Config.h`

Adicionar intervalo dos logs de metricas:

```cpp
static constexpr unsigned long MQTT_LOG_INTERVAL_MS = 60000;
```

## `MQTT.cpp`

- Remover publicacao em `sts/{device_id}`.
- Remover publicacao em `pir/{device_id}`.
- Remover comando manual de logs `{"stats": true}`.
- Publicar tudo em `log/{device_id}`.
- Nao enviar `state`; status e representado por `kind=status`.

## Payloads

Status, sempre com `retain=true`:

```json
{
  "kind": "status",
  "status": "working"
}
```

Last Will:

- topico: `log/{device_id}`
- payload: `{"kind":"status","status":"offline"}`
- `retain=true`
- QoS preferencial: `1`

Metricas, a cada `MQTT_LOG_INTERVAL_MS`, com `retain=false`:

```json
{
  "kind": "metrics",
  "heap_free": 120000,
  "psram_free": 3000000,
  "now_ms": 123456,
  "rssi": -62,
  "heap_min": 90000,
  "lesson": "AMBIENTAL",
  "remaining_ms": 60000,
  "next_ms": 0
}
```

PIR, ao detectar presenca, com `retain=false`:

```json
{
  "kind": "pir",
  "presenca": true
}
```

## Regras

- Apenas `kind=status` usa retain.
- `kind=metrics` e `kind=pir` nao sobrescrevem o status retido.
- `cmd/{device_id}` continua funcionando.
- O edge transforma `status`, metricas e `presenca` em capacidades InterSCity.
