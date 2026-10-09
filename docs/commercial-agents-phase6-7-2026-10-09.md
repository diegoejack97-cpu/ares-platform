# ARES — fases 6 e 7: carteira, propostas e decisão

Entrega local em 09/10/2026. Contrato oficial: [Agentes e ferramentas, seção 13.8](https://app.notion.com/p/3c7e18aa7b0d81cba5c3d6e7cce87585). Preservados Agno/OpenAI, Context Builder, Policy Layer, DecisionService, CRMProvider e Event Journal.

## Funcionalidades entregues

| Fase | Comportamento |
| --- | --- |
| 6 | Agentes separados `portfolio-prioritizer` e `commercial-analyst`; seleção SQL sobre todo o espelho autorizado antes do limite de contexto; ranking proposto, briefing e interpretação sem alterar prioridade/score Core. |
| 6 | Critérios de urgência, maior valor com moeda explícita, prazo e atratividade; totais exatos por moeda; recorte, fontes, validade e limitações visíveis. |
| 6 | Agenda por empresa, horários/dias/fuso, configuração versionada e auditada. Análise pessoal compartilhada entre Radar, Command Center e chat quando ator, critério e recorte coincidem. Perguntas com filtros/referências específicos continuam consultando seu próprio contexto. |
| 7 | `action-recommender` propõe ação, alternativas, riscos, contraindicações, lacunas e validade; `followup-writer` redige exclusivamente a tarefa/nota da ação validada. |
| 7 | Preparação manual pelo detalhe/chat e opt-in proativo por achado/carteira; limite diário por empresa, cooldown por oportunidade e unicidade por contexto. |
| 7 | Fila existente de Aprovações, aprovação humana para as novas propostas, revalidação antes de decisão/execução e recibo somente após confirmação do provider. |

São permitidas somente `create_task` e `add_note`. O modelo não escolhe empresa, negócio, destinatário, canal, SQL ou permissão. Nenhum envio de mensagens externas foi acrescentado.

## Ativação

Em **Agentes → Agentes comerciais**, o administrador da empresa configura:

1. Ativar análise da carteira — capacidade contratada de pelo menos três rotinas, contrato/entitlement ativos e orçamento existente.
2. Separar Recomendação e Follow-up — habilita o pipeline novo de intervenção, sem criar outra fila de aprovações.
3. Preparar propostas automaticamente — exige os dois controles anteriores, com intervalo mínimo e teto diário definidos.
4. Critério, moeda quando aplicável, horários, fuso, dias e motivo da alteração.

As flags começam desligadas. O ambiente local continua com elas desligadas após QA; foi conferido salvar/recarregar a agenda sem ligar IA nem cobrar chamadas. O catálogo e os comportamentos legados permanecem compatíveis. Propostas novas usam `recommendation.v3` e política de revisão humana versionada; regras legadas não foram alteradas para simular esta entrega.

## Persistência e segurança

Migration aditiva `20261009024812_commercial_agents_phase6_7.sql`, aplicada no Supabase local e no PostgreSQL isolado: **28 migrations locais**. Tabelas `commercial_routines`, `portfolio_analyses`, `commercial_proposals` e `recommendation_context_guards` têm RLS e acesso direto negado a `anon`/`authenticated`; controle acontece na API autenticada.

Runs independentes, schemas fechados, definição/hash, correlação, parent run, snapshot, uso e budget preservam rastreabilidade. IDs, referências e claims estruturados são validados fora dos modelos. Cada etapa comercial tem timeout de 95 segundos. Dispatch duplicado não inicia outra chamada; recuperação após envio incerto não reenvia automaticamente. Reservas anteriores a um bloqueio sem dispatch são liberadas; resultado incerto conserva tratamento conservador.

Mudanças de membership/carteira, configuração, contrato, versão ou contexto bloqueiam consumo/publicação antiga. Uma proposta pendente desatualizada pode ser substituída, mantendo a anterior como `superseded` e encerrando a intervenção anterior. Expiração da proposta, guard, policy e aprovação coincide. Antes de executar, o mesmo caminho de execução revalida policy, capability, identidade e contexto; transições internas próprias não invalidam indevidamente o guard. Idempotência e tratamento de timeout do CRM continuam no DecisionService existente.

## Validação local

- 249 testes unitários; Ruff e mypy sem erros em 119 arquivos de código.
- 158 casos PostgreSQL exercitados na regressão geral; a pausa prolongada do ambiente causou um timeout de conexão. O caso afetado foi repetido e passou, assim como os nove casos novos e a regressão direcionada de chat/propostas (22 casos).
- Testes novos verificam candidato antigo de alto valor além dos oito recentes, totais SQL, identidade compartilhada do painel/chat, seller/revogação, concorrência, saída com candidato inválido, proposta desatualizada, validade e uma única execução após aprovação no FakeCRM.
- 72 testes pgTAP, incluindo os 16 novos de existência, RLS e grants das tabelas comerciais.
- 112 testes frontend passaram numa execução limpa; typecheck, lint e build passaram; lint preserva nove warnings já existentes em componentes externos à entrega.
- Navegador: configuração/persistência sem ativação, painel de carteira nas telas operacionais, teclado, console e larguras 1440/820/390. Evidências locais ficam em `output/agent-phase6-7-2026-10-08/`, ignorado pelo Git.

## Limites e publicação

Validação realizada com dados sintéticos e FakeCRM, sem chamadas ao modelo real para estes testes. Isso confirma contratos, controles e fluxo, não a qualidade semântica de todas as interpretações. Avaliação de respostas com modelo real, homologação do CRM real e validação do ambiente hospedado permanecem necessárias. Não afirmar completude do CRM sem reconciliação; ranking por IA não representa previsão, causalidade nem receita incremental.

RAG/memória comercial e avaliação de resultados pertencem às fases 8 e 9. A fase 0 e os gates de operação/piloto da fase 10 continuam independentes. Para publicar, aplicar a migration no ambiente de destino e reconstruir API, worker e frontend; o pacote Docker anterior não contém automaticamente esta entrega. Rollback de aplicação desativa flags e preserva tabelas/auditoria, sem excluir evidências.
