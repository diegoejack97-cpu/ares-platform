# ARES — verificação dos fluxos, 05/10/2026

> **Atualização após as correções:** o resultado desta rodada e o roteiro de publicação estão em [Preparação da apresentação](presentation-release-2026-10-05.md). As pendências e falhas descritas abaixo registram o diagnóstico inicial; consulte o documento novo para distinguir o que foi corrigido dos limites que permanecem.

Os fluxos principais foram exercitados no Chrome com autenticação, API, PostgreSQL, worker local e FakeCRM HTTP. Foram verificadas escritas e persistência, além da aparência dos botões. Há integração comprovada entre várias abas; ainda existem pendências que impedem declarar o SaaS pronto para produção.

**Veredito:** demonstração assistida com dados sintéticos é viável, desde que o contrato esteja corretamente configurado. Piloto com dados reais depende das correções comerciais e operacionais abaixo e da homologação de um CRM real. O sucesso com FakeCRM não comprova essa homologação.

## Ambiente e limites

- Frontend local em `http://localhost:5173`, API em `http://127.0.0.1:8000` e FakeCRM HTTP em `http://127.0.0.1:8011`.
- Supabase local com 20 migrations aplicadas. O banco existente não foi resetado.
- Sessões reais de administrador da empresa, operador da Central Admin, auditor sintético e administrador de uma segunda empresa sintética. Credenciais não fazem parte deste relatório.
- Dados sintéticos; nenhuma escrita em CRM de cliente, envio de convite por e-mail, implantação pública ou publicação de código.
- Treze rotas conferidas no desktop, incluindo a entrada separada da Central Admin. Doze telas internas verificadas em 820 e 390 px.
- O contrato normativo continua na [documentação de produto](https://app.notion.com/p/3c0e18aa7b0d801d8898d2402fc737b3). CRM externo é a autoridade do funil; negócio do CRM e oportunidade ARES são entidades distintas.

## Correções realizadas nesta verificação

| Falha observada | Correção | Prova posterior |
| --- | --- | --- |
| Criar tarefa e nota no laboratório falhava no navegador antes do POST: preflight CORS retornava 400. | A API aceita o cabeçalho `Idempotency-Key`, preservando a lista de origens permitidas. | Os dois botões enviaram a ação e aumentaram os respectivos registros no FakeCRM HTTP. Regressão de preflight adicionada. |
| Uma aprovação aparecia como executada, mas não criava tarefa no CRM que alimentava o funil. O executor usava FakeCRM interno; laboratório, funil e integração usavam HTTP. | Perfil local de exemplo e bootstrap usam `http_fake`. A configuração local foi alinhada ao servidor HTTP em execução. | Nova aprovação criou exatamente uma tarefa no mesmo FakeCRM HTTP; repetir a decisão não duplicou a tarefa. Não se trata de resolução de provedores por empresa. |
| Pergunta genérica pedindo “nomes, etapas e valores salvos” retornava consulta vazia porque “nomes” virava filtro de nome. | Normalização da busca reconhece “nome/nomes” como termos genéricos. | A pergunta original retornou tabela com oito registros e fontes; busca por um nome específico continua preservada no teste de regressão. |
| Link de contrato do laboratório apontava sempre para a porta 8010. | API informa a URL de documentação do sandbox configurado; interface usa essa URL. | Link para a porta 8011 respondeu 200. Testes verificam configuração da URL sem expor a chave do provedor. |
| Editor de plano dizia que capacidade de sentinelas acima de um não funcionava, apesar do catálogo configurável já existente. | Texto explica o limite de regras ativas e que aumentar a capacidade não cria regras automaticamente. | Capacidade alterada pela Central Admin, regra criada pela empresa e capacidade original restaurada ao encerrar o teste. |

O Journal inicialmente apresentou largura transitória durante o redimensionamento do gráfico. Após aguardar o reflow, o documento permaneceu em 390 px, sem overflow da página. Não foi aplicada uma correção CSS desnecessária. Tabelas e Kanban podem continuar tendo rolagem interna para manter seus dados legíveis.

## Fluxos e ações confirmados

| Área | Ações exercitadas | Resultado e ligação com outras abas |
| --- | --- | --- |
| Estrutura do sistema | Menu, fechamento por Escape, troca de tema, sino e atualização de notificações. | Controles responderam; atualização consultou a API. |
| Radar e leituras operacionais | Atualização; sete alternâncias entre gráfico e tabela; leituras de Journal, Agentes, Command Center, Chat e Impacto. | Respostas da API confirmadas; detalhe da oportunidade usado na cadeia de aprovação. Limitação de paginação descrita abaixo. |
| Funil CRM | Abrir mudança, cancelar sem escrita, confirmar mudança e restaurar etapa original. | Cancelar não enviou comando. Duas mudanças confirmadas no provedor e na versão do cartão; execução identificada como ação humana, sem atribuir intervenção à IA. |
| Aprovações e detalhe | Solicitar recomendação, abrir edição, cancelar edição, aprovar e repetir a decisão. | Recomendação `agno_openai`, tarefa criada no HTTP, estado executado no detalhe, retirada da fila e repetição recusada com 409 sem tarefa adicional. O caso sem cobrança configurada foi bloqueado posteriormente pelo executor, conforme pendência abaixo. |
| Impacto | Consultar a mesma intervenção, atualizar e baixar CSV/PDF. | Intervenção vinculada à execução encontrada. `incremental_value` permaneceu nulo; não foi inventada receita incremental. Downloads geraram CSV de 16.102 bytes e PDF de 24.904 bytes com assinatura válida. |
| Integração CRM | Sincronizar alterações, reconciliar funil e carregar histórico. | Três jobs enfileirados pela interface terminaram em `succeeded` no worker: respectivamente 1, 60 e 37 registros nos recibos desta execução. |
| Sentinelas | Criar regra com agendamento, esperar execução, pausar e arquivar. | Criação 201, execução agendada registrada com 25 achados, pausa persistida e arquivamento 204. O teste não comprova drenagem completa do backlog. |
| Chat | Shift+Enter, Enter, limpeza imediata do compositor, três pontos, saudação e pergunta genérica, recarregamento. | Shift+Enter não enviou; Enter enviou; resposta curta para “oi”; tabela de dados para a pergunta genérica; mensagens persistiram. O resultado informa que é um recorte, não o total do funil. |
| Entrada de leads | Triar, confirmar criação, mesclar duplicado, desfazer mescla e descartar. | Estado e recibo HTTP persistidos; mescla, desfazer e descarte concluídos. O sandbox retorna identificador de lead, mas não oferece leitura independente desses leads; portanto a prova da criação é o recibo do provedor, não uma lista posterior de contatos. |
| Usuários e licenças | Registrar/cancelar convite, ativar conta previamente verificada e desativar membro. | Reserva liberada no cancelamento; papel Auditor confirmado; gestão de licenças, Central Admin e escrita em sentinelas recusadas pelo backend. O botão de criar regra ficou oculto para Auditor. Não houve envio de e-mail. |
| Central Admin | Configurar plano, vencimento, cotas, cobrança e administrador inicial; liberar e suspender empresa sintética. | Sessão do operador separada da sessão da empresa. Alterações persistidas e acesso negado após suspensão. Não foram exercitados todos os cenários de tolerância/vencimento por calendário. |
| Isolamento entre empresas | Entrar na empresa B após sair da A; consultar oportunidade da A e histórico do chat. | Empresa e plano próprios de B; oportunidade de A retornou 404; histórico B vazio. Funil B retornou 503 `client_crm_adapter_not_configured`, explicitando a ausência de adapter. Isso comprova as verificações exercitadas de isolamento, não uma integração multi-CRM pronta. |
| Laboratório e Journal | Documentação, seis simulações de falha, tarefa, nota, evento no laboratório e simular evento no Journal. | Falhas classificadas como 401/404/409/429/500/timeout; tarefa e nota confirmadas na fonte HTTP; evento encontrado no Journal pelo identificador/correlação; simulação do Journal aceita com 202. |

## Pendências e melhorias priorizadas

| Prioridade | Evidência / problema | Trabalho necessário |
| --- | --- | --- |
| P0 — antes do piloto | **Cobrança ausente tem comportamento divergente.** `billing_status` retorna `unconfigured` com `degraded=false`, enquanto `check_execution_contract` bloqueia a ausência. Na prática, foi possível aprovar e só depois obter cancelamento `billing_degraded`. | Unificar a regra entre consulta, IA, leads, aprovação e execução; mostrar ausência de configuração; recusar a aprovação inviável antes de criar intenção/job. Preservar a revalidação imediatamente antes da escrita externa. |
| P0 — antes de operação sem acompanhamento | **Retomada do executor não comprovada.** Worker local consome `integration.sync`/`integration.project` e agenda sentinelas. Execução de ações depende do disparo em background da API/tick. | Configurar consumidor supervisionado de `action.execute`; testar queda da API após enfileirar e após envio ao provedor, retomada e consulta idempotente sem duplicação. O risco foi identificado no código; não foi feito ensaio de queda durante uma escrita. |
| P0 — antes de dados reais | **Provider/credenciais por conexão e CRM real ainda pendentes.** B fica explicitamente sem adapter; ajustar o perfil global do FakeCRM não resolve esse problema. | Resolver adapter e segredos pela empresa/conexão, homologar CRM escolhido, webhooks duráveis, mapping, paginação, reconciliação, conflitos e escrita aprovada. Testar empresas com IDs externos iguais. |
| P1 | **Fila do Radar não busca páginas seguintes do servidor.** `getOpportunities` não recebe cursor; `RadarPage` revela lotes de cinco somente dentro de `items`, sem consumir `next_cursor`. | Implementar paginação da API ou consulta infinita, preservando ordenação/filtros; mostrar recorte e total corretamente. Achado por revisão de código, não por ensaio de todas as páginas do botão. |
| P1 | **Aviso de cota não discrimina reservas.** A mensagem explica “consumo e reservas”, mas os valores apresentados são consumo; há reservas pendentes que podem disparar o aviso mesmo com gasto exibido baixo. | Exibir consumido, reservado e disponível por período; reconciliar reservas interrompidas com evidência do provedor. Não liberar reservas desconhecidas nem aumentar orçamento para esconder o aviso. |
| P1 | **Sentinelas com processamento limitado por lote.** Foi comprovada uma execução com 25 achados; backlog completo e impacto de frequências elevadas não foram medidos. | Ensaiar drenagem, atraso, concorrência, quotas, mudança de horário/fuso e repetição diária em volume representativo. |
| P1 | **Operação hospedada e recuperação permanecem abertas.** | Staging com HTTPS, Supabase próprio, segredos/redirects/CORS, monitoramento de jobs e provedores, backup/restore e smoke pela URL publicada. |
| P2 | **Acabamento e desempenho.** Persistem nove avisos de lint e bundle principal de aproximadamente 933 kB / 288 kB gzip. Há um ícone decorativo grande no laboratório; o teste de SVG também detecta gráficos, não apenas ícones. | Revisar avisos, divisão de bundle, rótulos de etapas no chat e composição do laboratório. Acesso por Tab e axe parcial não substituem revisão completa de acessibilidade/UX. |

## Qualidade e evidências desta execução

| Verificação | Resultado |
| --- | --- |
| Backend sem PostgreSQL de testes | **174 passaram**, 67 testes de integração excluídos explicitamente por marcador. |
| Frontend completo | **96 passaram em 19 arquivos**, um worker e timeout de 15 segundos na CLI. |
| Lint | Ruff aprovado; frontend aprovado com nove avisos existentes. |
| Tipagem | mypy aprovado em 89 arquivos; TypeScript aprovado. |
| Formatação | Ruff: 132 arquivos já formatados; Prettier aprovado em todos os arquivos verificados. |
| Build | Aprovado; aviso de bundle principal grande permanece. |
| Desktop | Treze rotas carregadas; leituras esperadas da API retornaram 200; nenhuma exceção JavaScript não tratada capturada pelo inventário. Entrada da Central Admin verificada separadamente das ações autenticadas do operador. |
| Responsividade | Doze telas × duas larguras: **24 verificações sem overflow da página**, com foco por Tab. Menu/Escape e Enter/Shift+Enter também exercitados nos fluxos respectivos. |
| Acessibilidade automatizada | Sem violações classificadas como graves/críticas nos quatro recortes analisados: laboratório, licenças, chat e sentinelas. Não equivale a certificação completa de acessibilidade. |
| Graphify | Grafo atualizado por AST, sem extração semântica externa: 3.112 nós e 6.371 relações. |

Os 67 testes de integração Python e pgTAP relatados em 03/10 **não foram repetidos nesta auditoria**. As ações acima usaram o PostgreSQL local existente e o provedor HTTP real do sandbox, sem interceptar respostas de API. Testes unitários com stubs são evidência complementar, não a prova das escritas ponta a ponta.

Evidências locais, na pasta ignorada pelo Git:

- [Inventário final das rotas](../output/playwright/flow-audit-2026-10-05/inventory.json).
- [Histórico das ações](../output/playwright/flow-audit-2026-10-05/actions.json).
- [Responsividade e axe](../output/playwright/flow-audit-2026-10-05/responsive.json).
- [Conferência do conteúdo com menu móvel fechado](../output/playwright/flow-audit-2026-10-05/responsive-content.json).
- [Execução incorreta com provider interno](../output/playwright/flow-audit-2026-10-05/decision-embedded.json) e [execução confirmada no HTTP](../output/playwright/flow-audit-2026-10-05/decision-baseline.json).
- [Restauração das configurações temporárias](../output/playwright/flow-audit-2026-10-05/fixture-cleanup.json).

O histórico bruto de ações preserva tentativas iniciais que falharam por seletores ou expectativas do script, além dos defeitos reais posteriormente corrigidos. Para sentinelas, o resultado final é `sentinel-resume`; a tentativa `sentinels` foi retomada após adequar a capacidade temporária. A preparação `billing-active` concluiu a escrita, mas seu resumo falhou ao acessar o estado original nulo; a restauração foi confirmada separadamente. Esses registros não devem ser interpretados como falhas atuais dos mesmos botões, nem apagados para produzir um relatório artificialmente verde.

## Estado deixado no ambiente

- Configuração do executor local usa o mesmo FakeCRM HTTP do funil.
- Capacidade de sentinelas da empresa principal restaurada para um; regra temporária pausada e arquivada.
- Cobrança da empresa principal restaurada à **ausência original**, com registro de auditoria. Portanto, aprovações externas nessa empresa continuam bloqueadas até configurar legitimamente a cobrança; o teste não deixou uma liberação comercial permanente.
- Auditor sintético desativado e empresa B sintética suspensa. Histórico e registros de auditoria preservados.
- Movimentação temporária do funil restaurada à etapa original. Registros sintéticos de eventos, achados, tarefas/notas e decisões foram preservados como evidência.
- Botão de reset do sandbox não executado, porque apagaria a fonte sintética usada na reconciliação desta auditoria.
- Frontend, API e FakeCRM continuaram disponíveis ao encerrar: três respostas 200 na [verificação final dos serviços](../output/playwright/flow-audit-2026-10-05/health-final.json).

Não foram cobertos todos os papéis/combinações de política, arraste do Kanban, toda consulta possível do chat, exclusões destrutivas, fluxo de e-mail/recuperação de senha, falha de infraestrutura em produção ou todos os botões em todos os estados. A lista acima define o que foi efetivamente confirmado e o que continua pendente.
