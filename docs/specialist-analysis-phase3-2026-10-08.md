# Fase 3 — triagem e diagnóstico especializados

Entrega local em 08/10/2026. Contrato alinhado ao capítulo oficial [Agentes e ferramentas, seção 13.5](https://app.notion.com/p/3c7e18aa7b0d81cba5c3d6e7cce87585).

## Implementação

A rotina `context-analysis` ganhou uma flag versionada por empresa, `specialists_enabled`. Quando habilitada, executa `opportunity-triage` e `opportunity-diagnosis`, com prompts, schemas, runs e repasse próprios. O catálogo histórico `context-analysis.v1` mantém seu hash e contrato; o novo catálogo é `opportunity-analysis.v1`.

A triagem classifica e propõe urgência/encaminhamento. O diagnóstico separa fatos, hipóteses, evidências favoráveis e contrárias, lacunas e revisão humana. Os agentes recebem contexto fechado, sem SQL, credenciais, consulta livre ou escrita no CRM. Score e prioridade final continuam determinísticos.

O Context Builder guarda a projeção exata, seu hash canônico e um fingerprint dos fatos relevantes da oportunidade, negócio e sinais. O limite conservador reserva 2.000 bytes para fatos mais 500 para metadados; os cortes são declarados. A análise vale por dez minutos. Alteração relevante ou vencimento impede consumo; novos eventos sem alteração desses fatos permitem reutilização. JSONB não invalida hashes por reordenar chaves.

Claims estruturados exigem caminho e valor literal existentes na projeção; referências devem pertencer ao contexto. IDs, números e datas literais no texto passam por verificação determinística. Isso não comprova a verdade semântica de toda frase, a adequação da urgência ou causalidade. Hipóteses continuam interpretações que precisam de confirmação.

O Follow-up usa o schema `recommendation.v2` quando consome triagem independente validada e atual. Nesse modo, o modelo não produz outra triagem; o servidor adapta a saída para consumidores históricos. Sem análise válida, o fluxo anterior continua disponível e fica identificado como `legacy_fallback` na saída/auditoria. A Policy Layer continua decidindo sobre ações.

Antes de publicar a recomendação, autorização e origem são rechecadas. Se os fatos mudarem durante a geração, nada é publicado; o run termina como falha e a intervenção é cancelada. Repasses inválidos, acesso revogado, capacidade reduzida e desligamento da flag não alimentam diagnóstico/decisão. Reutilizações guardam recibo idempotente: repetir a mesma solicitação devolve a execução original mesmo após mudança dos fatos; uma nova análise exige uma nova solicitação.

## Interface e ativação

O detalhe da oportunidade ganhou o painel compacto **Triagem e diagnóstico**, com fontes, validade, fatos, hipóteses, limitações e estados de carregamento, erro, ausência e análise desatualizada. A indisponibilidade da IA preserva as evidências e a leitura do Radar.

A flag começa desativada. A configuração administrativa nesta fase acontece pela API autenticada, não por um novo formulário na tela de Sentinelas:

1. Consultar `GET /api/v1/agents/catalog` para estado e versão atuais.
2. Habilitar a rotina por `PUT /api/v1/agents/routines/context-analysis`, com `enabled`, `expected_version` e `reason`.
3. Habilitar especialistas por `PUT /api/v1/agents/routines/context-analysis/specialists`, usando a versão retornada. Exige administrador persistido, contrato ativo e ao menos dois agentes permitidos no plano. Substitui a sequência da mesma rotina, sem consumir um terceiro slot.
4. No detalhe, **Analisar evidências** solicita contexto atual e `POST /api/v1/agents/workflows`; o worker processa a cadeia. O botão só aparece quando autorizado. `GET /api/v1/agents/opportunities/{id}/analysis` informa o estado atual.

Uma mudança invalida a análise existente; a atualização é solicitada pelo usuário. Disparo proativo por evento/agenda pertence às fases seguintes. Rotas antigas, cancelamento e consulta de workflows continuam disponíveis.

## Validação e limites

- Backend: **222 testes sem integração** e **138 testes PostgreSQL** aprovados; dez testes de integração específicos da fase 3.
- Banco local: **56 contratos pgTAP** aprovados. A migration `20261008152917_specialized_diagnosis.sql` foi aplicada sem reset; há **25 migrations** registradas e nenhuma empresa com especialistas ativados.
- Ruff e mypy aprovados. A suíte frontend completa passou anteriormente em **102 testes**, em sequência, após três timeouts na execução paralela. Após as últimas mudanças, os três testes do painel passaram novamente, assim como TypeScript, lint (sem erros, com avisos preexistentes), Prettier e build de produção. Uma segunda repetição completa ficou sem progresso e foi interrompida; não foi contabilizada como aprovada. A última suíte completa aprovada permanece a execução em sequência de 102 testes.
- Navegador: estados sintéticos pronto/desativado/fila/falha/degradado/desatualizado/erro, larguras 1440/820/390, ícones 20 px, teclado e referências. Sem overflow ou erros no fluxo normal; HTTP 503 foi provocado apenas para verificar recuperação.
- API real no navegador, após reiniciar o processo antigo: HTTP 200, estado `disabled`, nenhum botão de execução e nenhum erro de página. Os estados com análise pronta foram simulados na interface; a cadeia real foi validada com executores sintéticos no PostgreSQL.
- Graphify atualizado por AST local, sem extração semântica ou envio de conteúdo ao modelo.

Não houve chamada real à OpenAI nesta validação. Qualidade das interpretações, avaliação rotulada da fase 0, CRM real e ambiente hospedado continuam pendentes. Rebuild/restart de API e worker e aplicação de todas as migrations são necessários na implantação. O worker local antigo não foi ativado para chamadas de IA; a flag permanece desativada.

Sentinelas/notificações persistidas e fluxo sino → chat ficam nas fases 4 e 5. RAG e fine-tuning não fazem parte desta entrega.
