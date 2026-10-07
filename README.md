# ARES Platform

**Commercial Intelligence Operating System**

A ARES Platform é uma plataforma de inteligência comercial projetada para identificar oportunidades em risco, recomendar intervenções, coordenar ações autorizadas e medir o resultado comercial com rastreabilidade.

O objetivo não é vender apenas software. É localizar e recuperar valor que já existe no funil, mas se perde por demora, ausência de follow-up, propostas paradas, falta de responsável ou priorização incorreta.

> **Status em 07/10/2026:** MVP do ARES Connect implementado e validado localmente para
> demonstração assistida com dados sintéticos. A operação com dados de clientes depende
> da homologação do CRM real e da validação do ambiente hospedado.
>
> **Primeiro produto:** ARES Connect.
>
> **Última entrega:** correções de autorização/RLS, rate limit por usuário e empresa,
> atualização de dependências, CSP, proteção de webhooks e paginação do Event Journal.
> O projeto contém **22 migrations**, aplicadas no Supabase local. O pacote Docker de
> demonstração foi reconstruído e verificado em ambiente isolado.

## Produtos e módulos

- **ARES Core** — sinais, oportunidades, contexto, decisão, políticas, intervenções, ações, resultados e aprendizado.
- **ARES Connect** — conecta a inteligência do ARES ao CRM já utilizado pelo cliente, sem substituí-lo.
- **ARES CRM** — CRM nativo e agent-first, construído sobre o mesmo Core.
- **STELLAR** — módulo de atração, qualificação e preparação de oportunidades.
- **Impacto ARES** — métricas de risco, recuperação, influência, custos e resultado incremental comprovado.

## Foco do MVP

O primeiro MVP é o **ARES Connect**.

O CRM do cliente continua sendo a fonte oficial do funil. O ARES:

1. recebe e normaliza eventos;
2. detecta sinais e evidências;
3. identifica oportunidades que exigem ação;
4. recomenda a próxima ação;
5. aplica políticas e solicita aprovação quando necessário;
6. executa ações autorizadas de forma idempotente;
7. acompanha o resultado;
8. mede valor e custo com uma trilha auditável.

### Cadeia auditável

```text
OPORTUNIDADE
→ ESTADO ANTES
→ INTERVENÇÃO ARES
→ AÇÃO RECOMENDADA
→ DECISÃO / APROVAÇÃO
→ AÇÃO EXECUTADA
→ EXECUTOR
→ ESTADO DEPOIS
→ RESULTADO
→ VALOR
```

## Responsabilidade na atribuição

A plataforma diferencia:

- `sale_value` — valor observado da venda;
- `ares_influenced_value` — valor associado a uma intervenção válida do ARES;
- `incremental_value` — resultado adicional comprovado por método e evidência suficientes.

Participação ou influência não é apresentada automaticamente como causalidade. Sem evidência suficiente, `incremental_value` permanece nulo.

## Princípios de arquitetura

- monólito modular com fronteiras explícitas;
- um ARES Core compartilhado entre Connect e CRM;
- integração por contrato `CRMProvider` e adapters por fornecedor;
- FakeCRM para desenvolvimento e testes sem dependência do cliente;
- FakeCRM HTTP Sandbox com massa sintética determinística, falhas controladas e contract suite;
- Event Journal com inbox, outbox, jobs, idempotência e reconciliação;
- Postgres como persistência principal;
- multi-tenant com Auth, RLS e RBAC desde a primeira migration;
- Supervisor determinístico e Policy Layer versionada;
- agentes com tools restritas e outputs estruturados;
- auditoria e correlação ponta a ponta;
- nenhuma dependência estrutural de Make, Pipefy ou Argus.AI.

> **Regra operacional:** o LLM propõe; o código valida; a Policy Layer autoriza; o worker executa; a auditoria prova.

## Stack

### Frontend

- React
- TypeScript
- TanStack Query
- shadcn/ui + Tailwind CSS
- Apache ECharts, D3 e deck.gl
- cliente gerado a partir do OpenAPI

### Backend e dados

- Python
- FastAPI
- Supabase
- PostgreSQL
- Supabase Auth e RLS

### Inteligência e operação

- Agno
- OpenAI API
- GitHub Actions
- observabilidade e auditoria estruturadas

## Escopo evolutivo

A arquitetura preserva espaço para:

- Next-Best-Action e incrementalidade;
- Vendedor Agêntico 24/7;
- Conversation Intelligence;
- intenção comercial pré-lead;
- Agent-Ready Commerce.

Essas capacidades são evolução do produto. O MVP não inclui reinforcement learning, modelos causais avançados, contextual bandits, autonomia comercial irrestrita ou fechamento totalmente autônomo.

## Plano de desenvolvimento

| Sprint | Objetivo                                                                                          |
| ------ | ------------------------------------------------------------------------------------------------- |
| **M1** | Espinha dorsal: monorepo, migrations, RLS, Auth, Event Journal, contrato de intervenção e FakeCRM |
| **M2** | Inteligência: Signal Engine, Opportunity Engine, score, contexto, Radar e detalhe                 |
| **M3** | Decisão e ação: agentes, Policy, aprovação, execução idempotente e outcome                        |
| **M4** | Integração real: adapter do CRM, sync, reconciliação e write-back                                 |
| **M5** | Conversa, grafo e transparência dos agentes                                                       |
| **M6** | Multi-tenant, Impacto ARES, relatórios, exportações e piloto                                      |

Nenhuma credencial do CRM real é necessária para iniciar M1. O FakeCRM sustenta o desenvolvimento até a homologação do adapter do primeiro cliente.

## Estrutura inicial

```text
ares-platform/
├── apps/
│   ├── web/
│   └── api/
├── packages/
│   ├── contracts/
│   └── ui/
├── supabase/
│   ├── migrations/
│   └── seed.sql
├── docs/
├── .github/
└── README.md
```

A estrutura foi inicializada na M1 como monorepo npm. As fronteiras continuam explícitas: frontend React em `apps/web`, API FastAPI no pacote `backend`, entrypoint de deploy em `apps/api` e infraestrutura local em `supabase`.

## Execução local

Pré-requisitos: Node.js 20+, Python 3.12+ e Docker Desktop para o Supabase local.

```powershell
npm install
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\backend[dev]"
npm run db:start
npm run db:reset
npm run db:bootstrap
npm run dev
```

O frontend fica em `http://localhost:5173`, a API em `http://localhost:8000` e o FakeCRM HTTP
Sandbox em `http://localhost:8010/docs`. Instruções completas, incluindo Supabase, estão em
[`docs/local-development.md`](docs/local-development.md) e
[`docs/fake-crm-sandbox.md`](docs/fake-crm-sandbox.md).

## Documentação

A especificação técnica e de produto está organizada no Notion:

- [ARES Platform — Documentação Técnica e Produto](https://app.notion.com/p/3c0e18aa7b0d801d8898d2402fc737b3)
- [ARES Connect — MVP pronto para desenvolvimento](https://app.notion.com/p/3c3e18aa7b0d81b68a0bff83ed7fe9df)
- [Métricas e Impacto ARES](https://app.notion.com/p/3cae18aa7b0d81259da2cdf9286a0b23)

## Segurança

Nunca publique no repositório:

- chaves da OpenAI;
- tokens ou credenciais de CRM;
- segredos do Supabase;
- dados reais de clientes;
- payloads com informações pessoais;
- arquivos locais de ambiente.

Segredos serão fornecidos por variáveis de ambiente e mecanismos seguros de CI/CD.

## Situação do projeto — 07/10/2026

### Capacidades implementadas

| Área                        | Entrega e escopo confirmado                                                                                                                                                                                             |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Core, Radar e detalhe       | Sinais, oportunidades ARES, score explicável, contexto, evidências, responsável, SLA e fila priorizada.                                                                                                                 |
| Funil e integração          | Contrato `CRMProvider`, FakeCRM HTTP, mapeamento, sincronização, reconciliação e movimentação humana com confirmação. O adapter homologado nos testes é o sandbox.                                                      |
| Decisão e aprovação         | Recomendações estruturadas, Policy Layer, aprovação/edição/rejeição, controle de papel e validade, execução idempotente e outcome auditado.                                                                             |
| Chat ARES                   | Streaming, respostas formatadas, consultas genéricas, comparações, continuidade entre perguntas e ferramentas de leitura com acesso revalidado. OpenAI real foi exercitado com dados sintéticos; não houve fine-tuning. |
| Agentes e sentinelas        | Monitoramento, regras e agendamento de sentinelas, achados/notificações e execução por worker independente.                                                                                                             |
| Administração da empresa    | Usuários, convites, licenças e permissões restritos à empresa. Command Center reúne a visão operacional da conta.                                                                                                       |
| Central Admin da plataforma | Acesso separado para o dono do sistema; gestão de empresas, planos, vencimento, capacidades, cobrança e cotas de IA.                                                                                                    |
| Leads e Impacto ARES        | Deduplicação e mesclagem humanas, criação no FakeCRM, métricas com atribuição explícita e exportações CSV/PDF auditadas.                                                                                                |
| Isolamento e segurança      | Auth/RBAC/RLS, carteira própria do vendedor, conexão e segredos por empresa, rate limit, CSP e limite de corpo de 1 MB.                                                                                                 |
| Operação e publicação       | Fila persistida, worker supervisionado, heartbeat/readiness e pacote Docker Compose em `deploy/`, com perfil de demonstração e dados sintéticos identificados.                                                          |

M1–M3 e as capacidades locais de M5/M6 estão implementadas. A infraestrutura de M4 foi
verificada com FakeCRM; **a integração com um CRM real permanece pendente**. O piloto de
M6 realizado até aqui é sintético e local. ARES CRM nativo, STELLAR e demais capacidades
evolutivas não representam produtos homologados nesta entrega.

### Última validação

Os números abaixo correspondem ao checkpoint de **07/10/2026**; são resultados locais,
não uma certificação de produção ou garantia sobre qualquer implantação futura.

| Verificação            | Resultado                                                                                                                   |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Backend sem integração | 188 testes aprovados                                                                                                        |
| Integração PostgreSQL  | 86 testes aprovados                                                                                                         |
| Frontend               | 99 testes aprovados                                                                                                         |
| Contratos pgTAP        | 56 verificações aprovadas                                                                                                   |
| Qualidade e build      | TypeScript, mypy, Ruff, formatação e build de produção aprovados; lint frontend sem erros, com nove avisos existentes       |
| Dependências           | `npm audit` e `pip-audit` sem vulnerabilidades conhecidas; imagem backend reconstruída também verificada                    |
| Containers e proxy     | Readiness 200, CSP aplicada, corpo acima de 1 MB rejeitado com 413 e documentação da API desativada fora de desenvolvimento |
| Journal no navegador   | Paginação real de 50 eventos sem repetição, teclado e estados vazio/erro; desktop, tablet e celular conferidos              |

Os padrões configuráveis de rate limit são **120 requisições**, **20 mutações** e
**6 mensagens de chat por minuto**, por usuário e empresa. São token buckets, com
capacidade de pico e reposição gradual; renovar a sessão não reinicia os contadores.
Detalhes e limites operacionais estão no [relatório de correções de segurança](docs/security-hardening-2026-10-07.md).

### Pendências para publicação e operação com clientes

- [ ] Homologar o primeiro CRM real: adapter, credenciais, mapeamento, sync, reconciliação, conflitos e write-back.
- [ ] Implantar e validar o ambiente hospedado: aplicar as 22 migrations, reconstruir serviços, configurar domínio/TLS, Auth, redirects, CORS, CSP e proxy confiável.
- [ ] Provisionar o operador real da Central Admin e os administradores das empresas; verificar MFA, recuperação de conta e revogação/expiração de sessões.
- [ ] Configurar monitoramento, limites de tráfego no edge, backups e ensaiar a restauração completa do ambiente hospedado.
- [ ] Validar contas, planos, cobrança, capacidades, orçamento de IA e conexões de cada empresa no destino.
- [ ] Executar o smoke pela URL publicada e o piloto com o CRM real antes de operar dados de clientes.

O onboarding da demonstração é assistido. Cadastro público automático, homologação do
CRM real e SaaS aberto ao público não foram declarados concluídos.

### Relatórios e guia de publicação

- [Preparação e publicação da demonstração](docs/presentation-release-2026-10-05.md).
- [Verificação dos fluxos e botões](docs/flow-verification-2026-10-05.md).
- [Evolução conversacional do chat](docs/chat-conversation-2026-10-06.md).
- [Auditoria local de segurança — diagnóstico anterior às correções](docs/security-audit-2026-10-07.md).
- [Correções de segurança e evidências finais](docs/security-hardening-2026-10-07.md).

---

**ARES Platform** — inteligência comercial que transforma sinais, decisões e intervenções em resultados rastreáveis.
