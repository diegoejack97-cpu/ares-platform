# Fase 2 — contexto confiável e consultas comerciais

Data: 08/10/2026. Base: `40bb8e5`, branch `feat/visual-system-v2`.

Implementação da fase 2 do [plano de agentes](ai-agents-roadmap-2026-10-07.md). O contrato foi registrado e conferido na seção 13.4 do [capítulo oficial Agentes e ferramentas](https://app.notion.com/p/3c7e18aa7b0d81cba5c3d6e7cce87585). Preserva Agno/OpenAI, PostgreSQL, autorização persistida, Event Journal, Policy Layer e orçamento existente. Não houve chamada a modelo externo nos testes.

## Comportamento entregue

O Context Builder concentra as novas consultas de carteira, negócio, oportunidade ARES, regra de sentinela e intervenção. A cadeia da fase 1 usa seu leitor/projetor de snapshots legados, preservando as referências originais de estado anterior e posterior. O chat recebe uma projeção fechada antes da geração: o modelo não escolhe SQL, ferramentas de recuperação, empresa ou carteira.

Pedidos de total, contagem, soma e distribuição usam o resultado agregado pelo PostgreSQL, sem chamar o modelo. Listagens exibem uma amostra explicitamente limitada; o total corresponde ao universo autorizado da consulta. Zeros continuam sendo zeros, valores ausentes continuam ausentes e cada moeda tem sua soma própria. O comparador de valor não declara vencedor global entre moedas diferentes.

Exemplos de perguntas determinísticas: “quantos negócios temos hoje?”, “qual o total de negócios e valores?”, “quantas oportunidades estão em proposta?” e “quantos negócios foram criados hoje?”. “Hoje” sem referência a criação/mudança consulta a carteira atual; pedidos de criação/mudança aplicam uma janela no timezone da empresa. A interpretação livre de todos os períodos e perguntas ainda não é universal: para consultas precisas, a API aceita os filtros tipados abaixo.

Na continuidade da conversa, IDs são reconsultados. Valores apresentados numa mensagem anterior não viram fatos correntes. Revogação de acesso ou mudança dos dados invalida o contexto; o stream revalida antes de emitir conteúdo. Uma resposta interrompida não significa que o provedor cancelou uma chamada já recebida; a contabilidade existente continua registrando o consumo observado.

## Consulta, identidade e cobertura

`commercial-query.v1` valida entidade, referência, conexão, responsável, nome, etapas canônicas, moeda, período com timezone, campo temporal, ordenação, campos e tamanho da amostra (1–20). Períodos são `[since, until)` e limitados a 366 dias. Campos extras, SQL livre e referências inválidas são rejeitados.

A identidade de negócio usa empresa, conexão e ID externo. O registro canônico é escolhido **antes** dos filtros de carteira/etapa; um duplicado antigo não pode reaparecer como aberto ou conceder acesso a vendedor. Homônimos e IDs iguais de conexões diferentes não são mesclados. Duplicados encontrados são declarados. Esta entrega não altera a restrição existente de uma conexão por provedor em cada empresa.

Métricas: quantidade, soma e quantidade com valor por moeda, distribuição por etapa, SLA vencido de oportunidades relacionadas, campos ausentes, duplicados e transições de etapa no período para os negócios do recorte. A consulta temporal declara negócios excluídos por data de origem ausente. Não representa uma análise histórica completa de coortes ou previsão comercial.

Metadados registram conexão, último sync, watermark, cursor pendente e jobs de integração. `mirror_query_complete: true` significa que o agregado foi calculado sobre todo o espelho autorizado. **Não significa CRM completo**: `crm_sync_complete` permanece falso enquanto não houver prova de reconciliação. O chat não chama uma página do CRM para completar ou inventar um total.

## Snapshots, orçamento e cache

- A migration acrescenta autor, finalidade, consulta, projeção, hash, versão, validade e metadados à tabela `context_snapshots`. Novos contextos usam `opportunity_id: null`; os snapshots legados de intervenções não são sobrescritos.
- O resultado auditado guarda os agregados completos e a amostra limitada. A projeção entregue ao modelo cabe em 2.000 bytes UTF-8, usados como limite superior conservador de tokens, mais 500 tokens reservados para instruções/schema: orçamento de snapshot de 2.500. Registros/grupos omitidos ficam declarados; nenhum agregado é recalculado sobre a amostra.
- O orçamento acima é do snapshot/projeção. A chamada inteira inclui pedido, histórico e envelope e continua sujeita ao guard de custo; não se declara todo prompt como medido por esse contador de snapshot.
- Cache persistido por empresa, ator, papel/carteira, finalidade, intenção e versão dos dados, com TTL de 60 segundos. Alterações nas fontes e no acesso incrementam uma versão por empresa. A nova projeção não invalida a si mesma.
- O contador fica no schema privado, com RLS e sem grants ao navegador. Seu trigger tem `SECURITY DEFINER`, nomes qualificados, `search_path=pg_catalog` e execução direta revogada; permite que uma escrita já autorizada invalide o cache sem conceder acesso ao contador. Exclusão em cascata não recria contador de empresa removida.
- Leituras revalidam membership, status da empresa, entitlement Connect, autor e versão. Vendedor recebe apenas sua carteira pela API; a policy restritiva não permite que outro autor leia a projeção pelo Supabase. Nenhuma proteção global de requisição foi removida.

## APIs e operação

| Rota | Uso |
| --- | --- |
| `POST /api/v1/context/query` | Construir ou reutilizar contexto autorizado a partir de `QueryIntent` |
| `GET /api/v1/context/{context_ref}` | Ler o contexto do próprio autor enquanto acesso, versão e validade permanecem atuais |

Exemplo de corpo de consulta:

```json
{
  "entity": "portfolio",
  "stages": ["proposal", "negotiation"],
  "currency": "BRL",
  "open_only": true,
  "order": "value",
  "sample_limit": 8
}
```

As rotas retornam `Cache-Control: no-store`. Contexto vencido retorna conflito, referência inacessível não revela dados e falhas de banco retornam código seguro com correlação. A nova rota POST conserva o guard global existente de cobrança e mutações, mesmo sendo consulta sem escrita comercial; não foi criada exceção de acesso/rate limit. Contextos não concedem autorização para executar ações no CRM.

Migration: `supabase/migrations/20261008142220_trusted_context_queries.sql`. Aplicada atomicamente no Supabase local sem reset, preservando **291 snapshots existentes**. Histórico local: **24 migrations**. Nenhuma nova rotina de agentes foi ativada. Antes de hospedar: aplicar migrations, reconstruir imagens e reiniciar API/worker; a imagem de demonstração antiga não contém automaticamente este código.

## Verificação

Resultados locais com dados sintéticos:

- **211 testes de backend sem integração** aprovados.
- **128 testes PostgreSQL** aprovados, incluindo 13 de aceitação do contexto confiável.
- **56 contratos pgTAP** aprovados após a migration; inclui cadastro de membros pelo admin.
- Ruff, formatação e mypy aprovados; Graphify atualizado por AST local, sem extração semântica externa.

Os testes verificam totais além da amostra contra SQL de referência, zeros/NULL/moedas, carteira do vendedor, autor/empresa/finalidade do cache, revogação e downgrade de papel, alteração de dados, TTL, identidade por conexão, duplicados legados antes dos filtros, períodos, datas ausentes, campos tipados, SQL rejeitado, projeção/citações, preservação dos estados de intervenção, cascata de exclusão e continuidade do chat com valores atualizados. Métricas respondem sem modelo; revogação antes do stream impede divulgação.

Não houve alterações de tela nesta fase nem nova validação visual. A API e o chat foram exercitados em testes HTTP/stream e PostgreSQL. Homologação de CRM real, carga de produção e validação na URL hospedada permanecem pendentes.

## Próximas fases

Esta entrega prepara a evidência para agentes especializados; não implementa os agentes comerciais completos da fase 3, notificações pessoais/sino → chat, RAG ou fine-tuning. A baseline completa de avaliação da fase 0 também permanece pendente. O fluxo e as limitações de cada fase continuam no roadmap.
