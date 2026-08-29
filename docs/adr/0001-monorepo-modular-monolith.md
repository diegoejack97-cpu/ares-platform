# ADR 0001: monorepo com monólito modular

Status: aceito em 2026-08-29.

## Decisão

O ARES Platform usa um monorepo com frontend React/TypeScript e backend FastAPI
separados. O backend é um monólito modular: um deploy e um banco, com fronteiras
de domínio explícitas e testes de arquitetura.

## Estrutura

- apps/web: SPA React/Vite;
- apps/api: entrada fina para o deploy FastAPI;
- backend/src/ares: identidade, connectors, intake, journal, Core, Policy,
  actions, audit e analytics;
- packages: contratos TypeScript gerados e UI compartilhada;
- supabase: migrations, funções, seeds e testes de banco.

## Consequências

Frontend e backend podem ser implantados independentemente. O domínio Python não
importa FastAPI, Supabase, Agno ou SDK de CRM. Integrações implementam
CRMProvider; o MVP começa com FakeCRM.
