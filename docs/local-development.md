# Desenvolvimento local

## Pré-requisitos

- Node.js 20 ou superior;
- Python 3.12 ou superior;
- Docker Desktop iniciado.

O Supabase local usa Docker e pode consumir memória relevante. Pare os serviços ao terminar.

## Primeira execução

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

O bootstrap cria somente no ambiente local:

- usuário `admin@ares.local`;
- membership `admin` no tenant de demonstração;
- `.env`, `apps/web/.env.local` e `supabase/functions/.env` ignorados pelo Git.

A senha local é exibida pelo bootstrap. Nunca reutilize essas credenciais em ambientes compartilhados.

## Verificações das M1, M2 e M3

```powershell
npm run db:test
npx supabase db lint --level error
npm run quality
```

Para a prova completa, mantenha API e Supabase ativos e, em outro terminal, sirva a Edge Function:

```powershell
npx supabase functions serve fake-crm-webhook --env-file supabase/functions/.env --no-verify-jwt
npm run m1:verify
npm run test:e2e:m1 --workspace @ares/web
npm run m2:verify
npm run test:e2e:m2 --workspace @ares/web
npm run m3:verify
npm run test:e2e:m3 --workspace @ares/web
```

`m1:verify` comprova login, HMAC, recebimento, job, tick, Event Journal, correlação e bloqueio de acesso anônimo.

`m2:verify` comprova webhook e tick até oito sinais versionados, oportunidade consolidada, score com breakdown, contexto citável com hash e APIs autenticadas. O E2E de navegador percorre Journal → Radar → detalhe e falha se houver erro de console ou página.

`m3:verify` comprova recomendação estruturada, Policy Layer, conflito 409, edição humana, intent idempotente, worker, escrita no FakeCRM e resolução do alvo pelo `context_ref`. O E2E de navegador percorre a decisão completa e também falha por erro de console, overlay, falta de foco ou overflow móvel.

Na Policy M3, `add_note` é a única ação de baixo risco com `allow` e segue pelo worker com decisão sistêmica, intent idempotente e auditoria. `create_task` usa `require_approval`; `update_stage` usa `deny`. Ausência de capacidade no adapter sempre converte o resultado em `deny`.

`ARES_OPENAI_API_KEY` é opcional no desenvolvimento local. Sem chave, falha de modelo ou orçamento excedido, o ARES usa fallback determinístico, registra o modo degradado e mantém a aprovação humana. Nenhuma ação é perdida ou ganha autonomia adicional.

Para incluir o teste de integração PostgreSQL no pytest:

```powershell
$env:ARES_TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
python -m pytest backend/tests
```

## Tick em ambiente hospedado

A migration cria o job `ares-tick-every-minute` com `pg_cron` e `pg_net`. Ele permanece inerte enquanto os dois segredos não forem configurados no Vault do Supabase:

```sql
select vault.create_secret(
  'https://api.exemplo.com/api/v1/internal/tick',
  'ares_tick_url'
);
select vault.create_secret(
  'SEGREDO_FORTE_E_EXCLUSIVO',
  'ares_tick_secret'
);
```

O valor de `ares_tick_secret` deve ser idêntico a `ARES_TICK_SECRET` no backend. Não armazene o segredo em migration ou commit.

## Encerramento

```powershell
npm run db:stop
```

Depois, encerre o Docker Desktop se nenhum outro projeto estiver usando seus containers.
