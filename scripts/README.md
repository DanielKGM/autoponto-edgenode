# Scripts Operacionais

Scripts usados para preparar o broker MQTT, executar sync manual e instalar os
agendamentos de sincronizacao do AutoPonto Edge.

Execute todos a partir da raiz do repositorio. Isso e obrigatorio para
`init-mosquitto-password.sh`, que carrega `./.env`, e mantem os demais comandos
consistentes com os caminhos documentados.

```bash
chmod +x scripts/*.sh
```

## `init-mosquitto-password.sh`

Cria `infra/mosquitto/passwd` para os usuarios MQTT usados pelo projeto.

```bash
cp .env.example .env
# preencha MQTT_PASS_DEVICE e MQTT_PASS_SERVICE
./scripts/init-mosquitto-password.sh
```

O script:

- carrega `./.env`;
- usa `MQTT_PASS_DEVICE` para o usuario `device`;
- usa `MQTT_PASS_SERVICE` para o usuario `service`;
- recria `infra/mosquitto/passwd` com a imagem `eclipse-mosquitto:2`;
- deixa o arquivo com permissao `644`.

Depois de mudar qualquer senha MQTT, rode o script novamente e reinicie o
Mosquitto:

```bash
./scripts/init-mosquitto-password.sh
docker compose restart mosquitto edge-app
```

## `sincronizacao-edge.sh`

Executa um ciclo manual de sincronizacao dentro do container `edge-app`.

```bash
./scripts/sincronizacao-edge.sh
```

Equivale a:

```bash
docker compose exec -T edge-app python -m app.sync
```

Requisitos:

- `docker compose up -d` ja executado;
- container `edge-app` rodando;
- `.env` com `AUTOPONTO_API_URL`, `NODE_UUID`, `AUTOPONTO_API_TOKEN` e
  `FACE_EMBEDDING_ENCRYPTION_KEY` corretos;
- rede externa disponivel, quando o backend estiver fora da rede local.

O ciclo:

1. faz `GET /edge/pull/?node_id=<NODE_UUID>`;
2. valida e descriptografa embeddings;
3. substitui o snapshot Redis do dia;
4. publica `{"fetch": true}` em `cmd/{dispositivo_codigo}` para cada dispositivo
   recebido no snapshot;
5. envia presencas pendentes para `POST /edge/attendance/`.

Para rodar sync sem enviar presencas pendentes, use direto o modulo:

```bash
docker compose exec -T edge-app python -m app.sync --sem-presencas
```

## `atualizar-agendamentos-sincronizacao-edge.sh`

Gera ou atualiza o bloco AutoPonto Edge na crontab do usuario atual.

```bash
./scripts/atualizar-agendamentos-sincronizacao-edge.sh --dry-run
```

```bash
./scripts/atualizar-agendamentos-sincronizacao-edge.sh
```

O script le `data/horarios_ufma.json`, calcula execucoes antes de cada
`horario_inicio` e grava logs em:

```text
data/logs/sincronizacao-edge.log
```

Bloco gerenciado:

```text
# AUTOPONTO EDGE SYNC BEGIN
...
# AUTOPONTO EDGE SYNC END
```

Ao aplicar, ele remove tambem o bloco legado:

```text
# AUTOPONTO EDGE TAREFAS BEGIN
...
# AUTOPONTO EDGE TAREFAS END
```

Tarefas geradas:

- `@reboot sleep 300 && ...`: sync apos boot;
- `0 0 * * * ...`: sync na virada de dia;
- slots UFMA: um sync antes de cada `horario_inicio` em `data/horarios_ufma.json`.

Opcoes:

| Opcao | Efeito |
| --- | --- |
| `--dry-run` | Imprime a crontab resultante sem gravar. |
| `--json /caminho/horarios.json` | Usa outro arquivo de horarios. |
| `--antecedencia-minutos 10` | Agenda os slots 10 minutos antes do inicio. |
| `--sem-reboot` | Nao cria a entrada `@reboot`. |

Tambem e possivel definir a antecedencia por ambiente:

```bash
ANTECEDENCIA_MINUTOS=10 ./scripts/atualizar-agendamentos-sincronizacao-edge.sh
```

## Diagnostico Rapido

Ver crontab atual:

```bash
crontab -l
```

Ver log dos ciclos agendados:

```bash
tail -f data/logs/sincronizacao-edge.log
```

Executar sync manual e ver logs do servico:

```bash
./scripts/sincronizacao-edge.sh
docker compose logs --tail=100 edge-app
```

Se `sincronizacao-edge.sh` falhar antes de resposta HTTP, confira DNS/rede do
container. Se a API responder `400` com erro de `node_id`, o token pode ter sido
aceito, mas `NODE_UUID` nao corresponde ao no cadastrado no backend.
