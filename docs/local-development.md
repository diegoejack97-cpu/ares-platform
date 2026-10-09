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
Executar `npm run db:bootstrap` de novo redefine a senha do admin e o GoTrue encerra as sessões
abertas desse usuário: o navegador volta para a tela de login (a interface valida a sessão no
servidor ao carregar e ao voltar para a aba).

## Portas e recuperação da leitura

O endereço canônico é `http://localhost:5173/radar`, com a API em
`http://localhost:8000`. Vite usa `strictPort`: se 5173 estiver ocupada, não muda
silenciosamente para uma origem que o CORS da API não permite. Reutilize a instância
correta ou encerre somente o servidor duplicado. Overrides de porta devem alinhar
`VITE_API_URL` e `ARES_CORS_ORIGINS` explicitamente; não são a configuração padrão.

Se aparecer `Failed to fetch`, verifique a requisição autenticada, não apenas
`/openapi.json`: uma resposta HTTP 500 pode aparecer no navegador como erro de CORS.
Na ocorrência de 08/09/2026, a instância antiga da API 8000 retornava 500 e a API
8001 retornava os 25 registros existentes. O primeiro encerramento falhou e deixou
dois processos ouvindo em 8000. Após identificar e encerrar a árvore da instância
antiga, a nova API 8000 restaurou a leitura, sem alteração no banco. O teste no
navegador confirmou 25 oportunidades e atualização manual e automática com HTTP 200. Não foi isolada a exceção
interna daquela instância antiga; não atribuir o problema a RLS ou falta de dados.

Valide carregamento e atualização manual/automática, sem alterar a massa:

```powershell
npm run test:e2e:live --workspace @ares/web
```

## FakeCRM HTTP Sandbox — fundação da M4

`npm run dev` inicia frontend, API ARES e o sandbox. A documentação interativa do CRM fictício
fica em `http://127.0.0.1:8010/docs`.

Para validar o contrato HTTP isoladamente:

```powershell
npm run m4:sandbox:verify
```

Consulte [`fake-crm-sandbox.md`](fake-crm-sandbox.md) para configuração, massa de dados e cenários
de falha. O sandbox não significa que o adapter do CRM real foi homologado.

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

Para habilitar IA real, configure `ARES_OPENAI_API_KEY` somente no `.env` da raiz e
`ARES_OPENAI_MODEL=gpt-5.4`. Reinicie a API após alterar o ambiente. O chat e os agentes
de triagem/follow-up compartilham o modelo. O GPT-5.4 usa raciocínio médio, limite de
4.096 tokens de saída por chamada (incluindo raciocínio) e timeout de 90 segundos.
O registro em `backend/src/ares/ai/models.py` mantém os limites de execução alinhados
à reserva preventiva e às tarifas de entrada, cache e saída; GPT-5-mini continua suportado.
As recomendações usam um schema fechado na OpenAI e passam novamente pela validação
do domínio antes da Policy Layer.

A chave válida não substitui a cota: `tenant_quotas` precisa de orçamento diário e
mensal positivo, configurado pelo painel do provedor. O piloto M6 começa com zero;
os limites devem ser definidos explicitamente pelo responsável. A conversão BRL do
piloto usa a taxa sintética identificada em `rate_source`, não uma cotação de mercado.

Para incluir o teste de integração PostgreSQL no pytest:

```powershell
$env:ARES_TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:55422/postgres"
python -m pytest backend/tests
```

## Piloto sintético da M6

Com Supabase, API e sandbox no ar, o bootstrap cria o operador dedicado do provedor
(`provider-m6@ares.local`, credencial gravada em `output/runtime/m6-provider-credentials.json`,
ignorado pelo Git), três outcomes rotulados `[SINTETICO M6]` e a cota do tenant local
(10 licenças, orçamento de IA zero). Ele só executa contra `localhost`.

```powershell
npm run m6:bootstrap
npm run test:e2e:m6 --workspace @ares/web
npm run test:e2e:m6:provider --workspace @ares/web
npm run test:e2e:command-center --workspace @ares/web
```

O ensaio ao vivo faz login real como admin e como provedor, registra e cancela um convite,
cria e mescla um lead no FakeCRM, exporta CSV e PDF e valida `/admin`, `/licenses`, `/leads`
e `/impact` em 1440/700/390 px com axe. Evidências ficam em `output/playwright/m6-live/`.

Criação de lead exige um sandbox com `POST /v1/leads`. Se um sandbox M4 antigo ainda estiver
rodando na porta 8010, a `bridge` preserva seus dados em memória e acrescenta leads duráveis
em SQLite; aponte `ARES_FAKE_CRM_BASE_URL` para ela:

```powershell
python -m uvicorn ares.fake_crm_sandbox.bridge:app --port 8011
```

O `provider_audit` é imutável e impede apagar tenants já listados pelo provedor. Tenants
sintéticos que sobrarem de uma rodada de testes interrompida só saem com `npm run db:reset`.

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

Depois da migration `20260927020000_sentinel_sla_findings.sql`, o tick tambÃ©m verifica atÃ© 50 novos prazos de SLA vencidos por ciclo e registra um achado por oportunidade e prazo. `GET /api/v1/sentinels` mostra os achados atuais do tenant. Em desenvolvimento, `ares.workers.local` executa essa verificaÃ§Ã£o a cada 60 segundos. Sem um tick concluÃ­do, o Radar indica que ainda aguarda a primeira verificaÃ§Ã£o.

## Encerramento

```powershell
npm run db:stop
```

Depois, encerre o Docker Desktop se nenhum outro projeto estiver usando seus containers.
