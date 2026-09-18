# Command Center — execução em 17–18/09/2026

Fonte normativa: [05 — UX/UI e Telas Detalhadas, seção 2 "Home / Command Center"](https://app.notion.com/p/3c3e18aa7b0d81acb2dbf39cbbc334b9),
[16 — MVP em Três Meses, mapa de telas](https://app.notion.com/p/3c9e18aa7b0d810caecdc74de94dc34e)
e [14 — Demonstração Construída](https://app.notion.com/p/3c5e18aa7b0d8149bdc3cef94037a25a)
(com a ressalva de que as metas do protótipo foram inventadas e não são compromisso).
A identidade Observatório em produção é a referência visual, não o protótipo comercial.

A tela responde às duas perguntas do documento — "o que exige atenção agora?" e
"qual valor está em risco ou foi associado às intervenções?" — em `/command-center`,
com dados reais do tenant e definição em cada número. Nada foi inventado; nenhuma
linha existente foi apagada.

## Endpoint

`GET /api/v1/command-center?days=7|30|90` (aceita 1–365). Transação `repeatable read`
somente leitura, `statement_timeout` de 10 s, janela `[until − days, until)` em UTC.
Exige membership ativa no tenant do token e módulo `ares_connect` ativo; erro no
envelope `{ "error": { "code", "message", "correlation_id" } }` (`access_denied` 403,
`invalid_window` 422, `command_center_unavailable` 503 sem detalhes do driver).

Escopo por papel: vendedor lê só as oportunidades com `owner_user_id` igual ao seu
(`scope.mode = "own"`, sem custo de IA, que é medido por tenant); gestor e admin leem
agregados; auditor lê tudo sem ações. `capabilities` informa o que a tela pode oferecer:
`approve` (gestor/admin), `assign` (sempre `false`: não existe endpoint de atribuição) e
`fix_connection` (apenas em `development`, via Laboratório CRM).

## Blocos

- **Agora** (retrato na data da consulta): abertas em risco, críticas (prioridade 0),
  SLA vencido, próximas 6 h, sem prazo, sem responsável, aguardando decisão; valor em
  risco por moeda (negócios sem valor ou sem moeda contados à parte, moedas nunca
  somadas); fila prioritária com as 8 primeiras oportunidades na ordenação canônica do
  Radar; aprovações pendentes (não limitadas ao período); ações falhas no período;
  conexões degradadas/revogadas.
- **Impacto ARES**: reutiliza `ImpactService.snapshot` — as mesmas fórmulas de
  `/impact/summary`, nunca uma cópia. `incremental_value` só aparece com
  `attribution_level = incremental_proven` e método registrado; senão "Não comprovado",
  nunca zero. Custo de IA declara "N de M execuções com custo medido".
- **Análises** (ECharts, cada uma com tabela alternativa, definição, unidade, período,
  fonte e frescor): fluxo de atenção por dia (abertas, trabalhadas, executadas, falhas);
  funil de intervenção por coorte sobre `opportunity_state_transitions`, na ordem da
  máquina de estados; sinais por tipo empilhados por dia; mapa de calor de quando os
  sinais são detectados (horário de processamento, UTC).
- **Trilha recente**: os 25 eventos mais recentes entre transições de estado relevantes,
  decisões, execuções e outcomes, cada um com `correlation_id`; o Event Journal guarda
  a trilha completa.
- **Definições e limitações**: sempre visíveis; cada rótulo de métrica tem um botão que
  leva à sua definição (`#def-<chave>` funciona sem JS). Lista o que o painel não mostra:
  metas, ranking de equipe, funil de etapas do CRM, totais entre moedas, grafo.

Regras que a tela cumpre: dado ausente nunca vira zero; moedas separadas; influência
não é causalidade; horários em UTC; nenhuma mutação (aprovar e assumir apontam para as
telas existentes ou ficam desabilitadas com explicação).

## Verificação em 18/09/2026

- Backend com banco local: **150 passaram** (12 novos: 6 unitários de API/definições e
  6 de integração com fixture sintética e rollback — gestor, vendedor, negação,
  paridade com `ImpactService.snapshot`, funil/tendências/sinais/heatmap/atividade).
  Ruff, formatação e mypy limpos.
- Frontend: **73 testes** (13 da página, 2 do `stackedOption`), typecheck, lint e build.
  O ECharts saiu do chunk do shell (`index` de 1,24 MB para 910 KB) para o chunk
  `aresTheme`, ainda carregado com o Radar.
- Ensaio real no navegador (`npm run test:e2e:command-center --workspace @ares/web`):
  login, item de navegação ativo, figuras honestas ("Não comprovado", custo medido,
  dados sintéticos), quatro frames com tabela, salto de definição, abrir oportunidade,
  troca de período com nova requisição, 1440/700/390 px sem overflow e sem violações
  axe (WCAG 2.1 AA), foco de teclado, temas claro e escuro. Evidências em
  `output/playwright/command-center/`.
- Correções feitas nesta rodada: alias `day` reservado no SQL; "expirando em 6 h" conta
  só expirações futuras; classe `.timeline` colidia com o detalhe da oportunidade
  (renomeada para `.event-trail`); rótulos do bloco Agora sem quebra; datas absolutas em
  vez de "há N min" para frescor de dias.

Reprodução:

```powershell
npm run dev
npm run test:e2e:command-center --workspace @ares/web
```

## Pendências fora do código

1. O protótipo do Notion não foi comparado visualmente; a tela seguiu os excertos das
   páginas 05, 14 e 16 e a identidade Observatório em produção.
2. `GET /metrics/:metric_id` (catálogo parametrizado) não existe; as definições viajam
   inline na resposta.
3. Não há fuso por tenant; UTC é declarado em cada bloco.
4. "Assumir" precisa de uma mutação de atribuição com `expected_version`/409 antes de
   ser habilitado.
5. `/impact/summary` continua com o envelope `detail={"code"}`; o Command Center usa o
   envelope `{ "error": … }` do plano.
6. A trilha não tem cursor (25 mais recentes); o Event Journal cobre o restante.
7. Não existe conta de vendedor no ambiente local; o escopo próprio está provado
   apenas pelo teste de integração Postgres.
