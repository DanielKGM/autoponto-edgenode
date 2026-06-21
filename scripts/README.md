# Scripts Operacionais

## Sincronizacao Manual Do Edge

Use estes scripts quando precisar disparar um ciclo pelo Linux, sem criar endpoint HTTP no `edge-app`.

```bash
./scripts/sincronizacao-edge.sh
```

O script executa o pull snapshot autoritativo (`python -m app.sync`).

## Agendamentos De Sincronizacao

O edge nao busca horarios padrao UFMA na API principal. O agendamento usa somente `data/horarios_ufma.json`.

Para revisar as tarefas que seriam gravadas, sem alterar a crontab:

```bash
./scripts/atualizar-agendamentos-sincronizacao-edge.sh --dry-run
```

Para gravar ou atualizar as tarefas:

```bash
./scripts/atualizar-agendamentos-sincronizacao-edge.sh
```

O script recria apenas o bloco entre `# AUTOPONTO EDGE SYNC BEGIN` e `# AUTOPONTO EDGE SYNC END`. Se existir um bloco antigo de tarefas locais, ele tambem sera removido.

Tarefas geradas:

- `@reboot`: sync snapshot apos 300 segundos.
- `00:00`: sync snapshot na virada de dia.
- Slots UFMA: sync snapshot antes de cada `horario_inicio` em `data/horarios_ufma.json`.

Por padrao, os slots sao agendados 5 minutos antes do horario. Para mudar:

```bash
./scripts/atualizar-agendamentos-sincronizacao-edge.sh --antecedencia-minutos 10
```

Para usar outro JSON:

```bash
./scripts/atualizar-agendamentos-sincronizacao-edge.sh --json /caminho/horarios.json
```
