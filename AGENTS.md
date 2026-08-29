# ARES Platform — instruções do projeto

## Autoridade e fonte da verdade

- A solicitação explícita do usuário tem precedência.
- A árvore [ARES CRM MVP — Documentação Técnica e Produto](https://app.notion.com/p/3c0e18aa7b0d801d8898d2402fc737b3) é a fonte oficial de produto, arquitetura, UX/UI, critérios de aceite e backlog.
- Páginas marcadas como histórico ou superadas não fundamentam novas decisões.
- Contratos executáveis, migrations e testes do repositório devem refletir o Notion. Se houver conflito material, não escolher silenciosamente: registrar a divergência e alinhar a fonte oficial antes de avançar.

## Produto e arquitetura

- ARES Connect é o primeiro produto e o CRM externo continua sendo a fonte oficial do funil.
- Preservar React/TypeScript, FastAPI, Supabase/PostgreSQL, Agno/OpenAI, monólito modular, CRMProvider/FakeCRM, Event Journal, Policy Layer e auditoria ponta a ponta.
- Não confundir negócio do CRM com Oportunidade ARES.
- Toda intervenção deve permitir reconstruir oportunidade, estado anterior, recomendação, decisão, execução, executor, estado posterior, resultado e valor.
- Influência ou associação não é causalidade. Nunca apresentar `ares_influenced_value` como `incremental_value`.

## Frontend

- Usar a skill `ares-frontend-engineering` em implementações de telas, dashboards, gráficos, tabelas, Kanban e estados de interface.
- Usar a skill `ares-visual-identity` quando a tarefa criar ou alterar linguagem visual, tokens, composição ou componentes.
- O protótipo documentado no Notion é a referência visual normativa. Não substituir sua identidade por defaults de bibliotecas.
- ECharts é a biblioteca padrão para gráficos operacionais. D3 é reservado a visualizações ou layouts realmente customizados. deck.gl é reservado a camadas geoespaciais ou visualizações WebGL de grande volume e deve ser carregado sob demanda.
- Não combinar ECharts, D3 e deck.gl no mesmo componente sem necessidade técnica demonstrável.
- Toda visualização crítica precisa de título, definição, período, fonte, frescor, estado de carregamento/vazio/erro e alternativa acessível em tabela ou lista.

## Qualidade e segurança

- Executar lint, typecheck e testes relevantes antes de concluir uma mudança quando esses comandos existirem no projeto.
- Mudanças visuais precisam de verificação no navegador, estados responsivos, navegação por teclado e ausência de erros no console.
- Nunca incluir segredos, tokens, dados reais de clientes ou payloads com PII no frontend, fixtures, screenshots ou logs.
- Strix está adiado. Não instalar, configurar ou executar Strix sem nova autorização explícita.
- Graphify não pode instalar pacotes, hooks ou enviar documentação para um modelo externo sem autorização específica.

## graphify

This project can generate a local knowledge graph at `graphify-out/` with god nodes, community structure, and cross-file relationships. The generated directory is ignored by Git and must be rebuilt in each checkout.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- No strict or post-commit Graphify hook is installed. Generated files may change after explicit builds or incremental updates; this is not a reason to skip a valid local graph.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- Do not run semantic extraction over documentation or send repository content to an external model without explicit user approval.
