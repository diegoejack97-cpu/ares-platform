# ARES Platform

**Commercial Intelligence Operating System**

A ARES Platform é uma plataforma de inteligência comercial projetada para identificar oportunidades em risco, recomendar intervenções, coordenar ações autorizadas e medir o resultado comercial com rastreabilidade.

O objetivo não é vender apenas software. É localizar e recuperar valor que já existe no funil, mas se perde por demora, ausência de follow-up, propostas paradas, falta de responsável ou priorização incorreta.

> **Status atual:** Sprint M1 em andamento — monorepo, primeira fatia vertical e contratos canônicos implementados.
>
> **Primeiro produto:** ARES Connect.
>
> **Próximo marco:** concluir a validação local das migrations/RLS e integrar Supabase Auth à fatia vertical.

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

| Sprint | Objetivo |
|---|---|
| **M1** | Espinha dorsal: monorepo, migrations, RLS, Auth, Event Journal, contrato de intervenção e FakeCRM |
| **M2** | Inteligência: Signal Engine, Opportunity Engine, score, contexto, Radar e detalhe |
| **M3** | Decisão e ação: agentes, Policy, aprovação, execução idempotente e outcome |
| **M4** | Integração real: adapter do CRM, sync, reconciliação e write-back |
| **M5** | Conversa, grafo e transparência dos agentes |
| **M6** | Multi-tenant, Impacto ARES, relatórios, exportações e piloto |

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
npm run dev
```

O frontend fica em `http://localhost:5173` e a API em `http://localhost:8000`. Instruções completas, incluindo Supabase, estão em [`docs/local-development.md`](docs/local-development.md).

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

## Situação do projeto

- [x] arquitetura e stack definidas;
- [x] PRD e critérios de aceite consolidados;
- [x] modelo de dados canônico definido;
- [x] plano M1–M6 fechado;
- [x] backlog inicial preparado;
- [x] monorepo inicializado;
- [ ] ambientes local e homologação configurados;
- [x] implementação da M1 iniciada;
- [x] primeira fatia vertical FakeCRM → Event Journal → interface validada;
- [ ] migrations e políticas RLS executadas localmente com Docker.

---

**ARES Platform** — inteligência comercial que transforma sinais, decisões e intervenções em resultados rastreáveis.
