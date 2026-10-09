# Chat ARES — interpretação e continuidade

## Problema confirmado

A pergunta `qual a melhor oportunidade que temos hoje` era transformada em busca textual: `melhor` virava filtro de nome. Uma busca vazia encerrava o fluxo antes de a IA interpretar o pedido. O histórico era exibido, mas não participava da interpretação de referências como `dessas` ou `por que essa?`.

## Correção

- A busca ordena comparações antes do limite de consulta. Maior valor considera negócios abertos; prioridade zero representa maior urgência ARES. Urgência e etapa não são probabilidade de fechamento.
- A IA recebe até três pedidos anteriores do mesmo usuário, empresa e escopo nas últimas 24 horas. Os fatos antigos das respostas não são reutilizados como evidência: os registros referenciados são consultados novamente.
- `get_context` fornece a evidência autorizada; `search_opportunities` permite consultar por nome/ID real, etapa canônica e ordenação, ou descobrir registros sem filtro. São filtros estruturados, sem SQL produzido pelo modelo. A pergunta inteira não deve ser usada como nome.
- Cada chamada revalida acesso. Duas novas consultas por resposta, até oito registros por contexto e três chamadas de ferramenta limitam custo e volume. Orçamento é reservado antes de chamar o modelo; consultas, evidências e resposta ficam vinculadas à execução auditada.
- Perguntas livres com busca inicial vazia passam à IA quando há modelo configurado. A IA pode consultar os registros disponíveis em vez de concluir que não há oportunidades. Sem modelo, permanecem saudação, listagem, comparação factual e declaração de dados ausentes.
- Uma referência como `dessas` mantém o universo da lista mencionada mesmo se a IA reformular a consulta. O histórico de outra empresa, usuário ou oportunidade não entra na conversa.
- Negócios do CRM e seus espelhos são reconciliados por conexão e ID externo, preservando os IDs dos registros ARES relacionados. Nomes iguais em conexões diferentes não são fundidos. A compatibilidade com IDs legados do FakeCRM fica restrita ao desenvolvimento.
- Etapas canônicas aparecem em português; zero é preservado, valor ausente fica ausente e moedas diferentes não são comparadas sem conversão.

O comportamento segue o uso explícito de [contexto no Agno](https://docs.agno.com/context/agent/overview), com armazenamento e autorização próprios do ARES. Não houve treinamento/fine-tuning do modelo nem criação de um segundo armazenamento de sessões.

## Validação

Regressões cobrem a sequência da captura, valor acima dos 101 registros mais recentes, negócios fechados, valores atualizados, referência removida, isolamento entre usuários/empresas/escopos, prioridade zero, moedas distintas, estágio atualizado no CRM, deduplicação e reformulação de pergunta livre com limites de ferramenta.

A versão final passou em **180 testes de backend sem integração e 82 testes PostgreSQL**, além de Ruff, formatação e mypy do módulo de chat. Os 13 testes PostgreSQL selecionados para chat também passaram separadamente.

A conferência no Chrome com a API e o modelo OpenAI configurados passou nas quatro perguntas: listagem, melhor oportunidade, motivo da escolha e onde concentrar esforços comerciais. Sem erro de JavaScript, resposta SSE incompleta ou negócio duplicado na comparação. A pergunta livre levou a uma nova consulta com ordenação por urgência e trouxe oportunidades concretas. Dados usados são sintéticos locais. Evidências ficam em `output/playwright/presentation-release-2026-10-05/`, ignorado pelo Git. Um teste intermediário revelou a necessidade dos filtros estruturados e foi corrigido antes do aceite.

## Limites de aceite

A consulta retorna recortes, não contagens ou somas globais do funil. A leitura do espelho consulta até 101 registros e a do adapter HTTP até cinco páginas; truncamento e indisponibilidade são declarados. A ferramenta de busca não configura sentinelas, aprova ações, altera o CRM ou administra usuários. O modelo deve explicar essa fronteira, sem prometer ações que não possui.

Esta entrega melhora interpretação, análise e continuidade sobre os dados consultáveis. Não comprova acerto de toda pergunta possível, probabilidade de fechamento, causalidade comercial ou homologação de CRM real. Mantém-se o aceite de apresentação assistida com dados sintéticos registrado na [preparação da apresentação](presentation-release-2026-10-05.md).
