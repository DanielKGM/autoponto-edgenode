# Prompt Para Refatorar O Firmware ESP32 AutoPonto

Voce esta trabalhando no repositorio do firmware ESP32 AutoPonto, nao no edge-node. Refatore o MQTT para separar status de logs e remover o comando manual de estatisticas.

Nao altere arquivos do repositorio `autoponto-edgenode`. Altere apenas o firmware.

## Objetivo

O firmware deve:

- manter status em `sts/{device_id}`;
- publicar logs automaticamente em `log/{device_id}` a cada 1 minuto;
- remover o comando manual `{"stats": true}`;
- nao enviar `state` nos logs, porque `state` e status;
- limitar o payload de logs aos campos usados pelo edge para publicar capacidades InterSCity.

## Topicos MQTT

Manter:

```text
cmd/{device_id}
sts/{device_id}
log/{device_id}
```

`cmd/{device_id}` continua recebendo comandos de autenticacao/feedback do edge.

`sts/{device_id}` continua sendo usado para status do dispositivo, por exemplo:

```text
working
idle
offline
```

`log/{device_id}` deve ser automatico e separado do status.

## Configuracao

Adicionar em `Config.h` ou no arquivo de configuracao equivalente:

```cpp
static constexpr unsigned long MQTT_LOG_INTERVAL_MS = 60000;
```

Se o projeto usa `Config_Model.h` ou uma estrutura persistida de configuracao, adicionar campo equivalente e default de 60000 ms.

## Remover Comando Manual De Logs

Em `MQTT.cpp`, remover a logica que espera comando do edge/Raspberry com payload semelhante a:

```json
{"stats": true}
```

O edge nao enviara mais comando manual para requisitar logs. O firmware deve publicar logs sozinho no intervalo configurado.

## Payload De Logs

Publicar em `log/{device_id}` apenas:

```json
{
  "rssi": -62,
  "heap_min": 123456,
  "lesson": "AMBIENTAL",
  "remainingms": 60000,
  "nextms": 0
}
```

Remover do log:

- `state`;
- `status`;
- `cpu_freq`;
- `heap_free`;
- `now_ms`;
- campos de PSRAM;
- stacks;
- objeto aninhado `context`;
- qualquer outro campo nao listado em `rssi`, `heap_min`, `lesson`, `remainingms`, `nextms`.

`state` nao deve existir no log porque ele representa status. Status deve ser publicado somente em `sts/{device_id}`.

## Sem Status Junto Dos Logs

Nao publicar status junto com logs. O fluxo esperado e:

```text
sts/{device_id} -> working|idle|offline
log/{device_id} -> JSON com rssi, heap_min, lesson, remainingms, nextms
```

O edge transformara `sts` na capacidade InterSCity `status` e transformara `log` nas capacidades `rssi`, `heap_min`, `lesson`, `remainingms`, `nextms`.

## Agendamento Automatico

Implementar controle simples por `millis()`:

```cpp
if (mqttConnected && millis() - lastLogPublishMs >= MQTT_LOG_INTERVAL_MS) {
    publishLog();
    lastLogPublishMs = millis();
}
```

Evitar publicar logs quando o MQTT estiver desconectado.

## Compatibilidade

Manter o comportamento existente de:

- conexao/reconexao MQTT;
- LWT/status offline se ja existir;
- recebimento de `cmd/{device_id}` para feedback de autenticacao;
- chamada de contexto HTTP ao edge, se ja existir.

## Testes Esperados

- Firmware publica `log/{device_id}` automaticamente a cada 1 minuto.
- Firmware nao publica log por comando `{"stats": true}`.
- Payload de log contem somente `rssi`, `heap_min`, `lesson`, `remainingms`, `nextms`.
- Payload de log nao contem `state` nem `status`.
- Status continua sendo publicado separadamente em `sts/{device_id}`.
- `cmd/{device_id}` continua funcionando.
