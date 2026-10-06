# ARES — preparação da apresentação desta semana

Esta entrega prepara uma **demonstração assistida com dados sintéticos**. O pacote de publicação está em `deploy/`. A homologação de um CRM real continua obrigatória antes de operar dados de clientes. Este documento complementa a [verificação dos fluxos](flow-verification-2026-10-05.md); os resultados antigos permanecem como histórico.

## Correções implementadas

| Ponto | Resultado |
| --- | --- |
| Cobrança e liberação | Contrato ausente bloqueia geração, aprovação, escrita e reservas de IA. A interface explica o bloqueio; a decisão inválida não cria intenção/job. A migration `20261005203936` aplica a mesma regra às políticas do Data API. |
| Execução independente | `ares.workers.daemon` consome a fila persistida de integrações e ações e agenda os sentinelas. O perfil de demonstração exige worker supervisionado, desativa execução em background da API e verifica heartbeat no readiness. |
| Retomada | Teste cobre lease expirado e resposta perdida após aceite do CRM, com retomada e uma única tarefa externa pela mesma chave idempotente. Bloqueio comercial continua terminal. |
| CRM por empresa | Manifesto no servidor vincula tenant, conexão, URL e referências a segredos próprios. Conexão trocada, revogada ou ausente é recusada. Chat, integrações e worker usam essa resolução. Teste com duas fontes HTTP e IDs externos iguais. O adapter implementado continua sendo FakeCRM HTTP. |
| Webhooks | API e seleção de segredos da Edge Function usam a conexão/empresa correspondente; o segredo compartilhado antigo fica restrito ao desenvolvimento explícito. A Edge Function não integra o pacote Compose de demonstração. |
| Radar | Consulta infinita usa o cursor da API, mantém lotes de cinco e deduplica fronteiras. Cache da navegação separado da fila. Teste alcança 27 linhas sem duplicar a fronteira. |
| Cotas | Aviso mostra consumido, reservado e disponível. Reserva de dia anterior não é somada ao reservado do dia atual. Custos desconhecidos permanecem reservados; não foram apagados nem tratados como consumo confirmado. |
| Sentinelas | Lote cheio é retomado após dez segundos, sem aguardar o próximo horário diário. Teste drena 71 achados sem duplicação. |
| Apresentação | Perfil explícito `demonstration`, identificação de dados sintéticos, laboratório/simulação de eventos ocultos fora de desenvolvimento. Ícone de indisponibilidade do laboratório limitado a 24 px. |
| Build e dependências | Radar e detalhe carregados sob demanda. JavaScript principal caiu de cerca de 933 kB para 486 kB; isso não equivale ao tamanho total da página. Dependências compatíveis atualizadas e gerador shadcn removido; CSS estático e licença preservados. `npm audit` retornou zero vulnerabilidades conhecidas. |
| Persistência do sandbox | Volume mantém dados e recibos idempotentes do FakeCRM após reinício. Arquivo inválido impede iniciar, em vez de restaurar a massa silenciosamente. Um único processo/instância de sandbox por volume. |
| Chat conversacional | Evolução em 06/10: interpreta comparações, retoma referências privadas, reconsulta fatos e oferece à IA filtros estruturados para reformular perguntas livres. Reconciliada a identidade do CRM com o espelho para evitar negócios duplicados. [Detalhes e limites](chat-conversation-2026-10-06.md). |

## Validação

- 178 testes de backend sem integração e 74 testes PostgreSQL aprovados até este checkpoint.
- Atualização do chat em 06/10: 180 testes sem integração e 82 PostgreSQL aprovados; quatro perguntas encadeadas/livres passaram no Chrome com OpenAI real e dados sintéticos. API e worker locais foram reiniciados com a correção. O teste das imagens Docker acima permanece o checkpoint de 05/10; reconstruir as imagens a partir do código atual antes de publicar.
- 56 verificações pgTAP aprovadas com a proteção de cobrança aplicada.
- 97 testes frontend aprovados; TypeScript, mypy, Ruff e formatação aprovados. Nove avisos existentes de lint permanecem, sem erros.
- Seletor de segredo de webhook passou no teste Node; não representa homologação completa da Edge Function hospedada.
- Banco descartável preparado com 20 migrations anteriores e a migration nova, sem copiar dados da aplicação local.
- Backup dos schemas da aplicação restaurado em banco novo: contagens iguais em 58 tabelas públicas. Schemas gerenciados, configuração de cron e default ACLs gerenciadas foram excluídos. Isso não substitui o restore completo do projeto Supabase hospedado.
- No Chrome local, após liberação auditada do contrato sintético: convite/cancelamento, cancelar/mover/restaurar etapa, três modos de sincronização no worker e chat genérico com dados passaram. Antes da liberação, as escritas retornaram 403, conforme a regra nova.
- Imagens Docker finais construídas com sucesso. No projeto isolado, CRM, worker, API e Caddy iniciaram; login, sete rotas, rótulo de demonstração, consulta genérica e API autenticada na mesma origem passaram no Chrome. Laboratório oculto no menu e acesso direto redirecionado.
- Reinício do CRM preservou a tarefa e o recibo idempotente. Worker parado tornou o readiness HTTP 503; o reinício restaurou HTTP 200. Caddy validou sua configuração. O teste usou HTTP em loopback; não é prova de certificado HTTPS público.
- Radar, aprovações, sentinelas, chat, detalhe da oportunidade, Command Center e licenças conferidos no Chrome em 1440, 820 e 390 px: 21 combinações sem transbordamento horizontal, erro de JavaScript ou resposta HTTP 5xx. Formulário do chat permaneceu dentro da tela nas três larguras; Tab/Escape e capturas com o menu fechado conferidos. Axe não encontrou ocorrências graves/críticas nas quatro telas de formulário em desktop e celular; é uma verificação parcial de acessibilidade.

Evidências locais, logs e credenciais de teste ficam em `output/`, ignorado pelo Git e excluído das imagens. A alteração preexistente em `.agents/skills/ares-visual-identity/SKILL.md` não faz parte desta entrega.

No ambiente local existente, as 21 migrations estão aplicadas, a API usa worker independente e o contrato da empresa sintética foi liberado pela Central Admin com justificativa e auditoria. Isso atualiza o estado registrado como histórico no relatório inicial, sem liberar uma empresa real. O banco local não foi resetado.

## Publicar a demonstração

1. Prepare um servidor com Docker Compose, domínio/DNS e portas 80/443, e um projeto Supabase separado para a demonstração. Aplique as **21 migrations** sem executar reset em bases com dados.
2. Crie contas verificadas no Supabase Auth para o dono da plataforma e o administrador da empresa de demonstração. Não use credenciais locais na internet. O dono não deve ter membership de empresa: sua sessão pertence à Central Admin.
3. Registre somente a conta do dono em `private.provider_operators`, por acesso administrativo ao banco, com motivo explícito. Essa tabela não pode ser gerida por um administrador de empresa. A configuração inicial é um procedimento assistido; não há promoção automática.
4. Copie `deploy/.env.example` para `deploy/.env` e substitua os placeholders. Configure Supabase, domínio, CORS, segredos aleatórios com pelo menos 24 caracteres e manifesto de conexões. Apenas URL/chave **pública** do Supabase entram no build do site. Os demais segredos ficam no servidor. Não execute `docker compose config` com saída em logs compartilhados, pois ele pode expandir o env.
5. Suba o pacote para acessar `/central-admin`. Crie uma empresa chamada **`[DEMO] ARES Connect`**, defina plano Connect, vencimento, usuários/agentes/sentinelas, orçamento e cobrança ativa; vincule a conta verificada do administrador. A existência de empresa, plano, cota e cobrança são liberações distintas.
6. Atualize `ARES_TENANT_ID` e o manifesto com o ID dessa empresa e um UUID exclusivo para sua conexão. Recrie os serviços para aplicar o env. Provisione somente a conexão da empresa marcada como demonstração:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T api python -m ares.connectors.configure_demo --confirm-synthetic
```

7. Entre como administrador da empresa, configure o mapeamento no Funil CRM e execute reconciliação. O FakeCRM ficará na rede interna, com volume persistente; API e worker também não têm porta pública direta. O site faz proxy da API na mesma origem.
8. No Supabase Auth, ajuste URL do site e redirects para o domínio HTTPS. Faça o smoke pela URL publicada: login, leitura do Radar, pergunta genérica, sentinela agendado, aprovação e tarefa confirmada, histórico/impacto e logout. Confirme `/health/ready` e os healthchecks do Compose.
9. Ative monitoramento externo de disponibilidade, erros/atraso da fila e orçamento. Configure backup do Supabase e do volume `crm_data` e ensaie recuperação no ambiente hospedado. Não execute `down -v`, pois remove volumes.

O Caddy segue os [padrões oficiais de SPA/proxy](https://caddyserver.com/docs/caddyfile/patterns), e a ordem de inicialização usa [healthchecks do Compose](https://docs.docker.com/compose/how-tos/startup-order/). A obtenção de certificado e o smoke público dependem do domínio e do servidor escolhidos; não foram declarados concluídos localmente.

## Limites para o cliente

Apresentar como demonstração do fluxo e das capacidades implementadas. Não declarar CRM real homologado, receita incremental comprovada, isolamento formalmente certificado ou SaaS aberto para cadastro público. Onboarding automático por e-mail/recuperação de senha, monitoramento contratado e restore integral do Supabase precisam de aceite próprio; nesta apresentação o onboarding é assistido. Reservas com custo desconhecido só podem ser conciliadas mediante evidência do provedor.

Fonte oficial de produto: [ARES CRM MVP no Notion](https://app.notion.com/p/3c0e18aa7b0d801d8898d2402fc737b3).
