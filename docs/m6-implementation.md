# M6 — execução iniciada em 15/09/2026

## Evolução do contrato por empresa (27/09/2026)

O painel `/admin` agora apresenta o diretório de empresas com pacote, estado de
liberação, vencimento, cobrança e número de licenças. Uma empresa nova começa
suspensa. O operador do provedor atribui um dos pacotes documentados
(`STELLAR`, `ARES Connect`, `ARES CRM`, completo com Connect ou completo com CRM),
define o vencimento, configura cobrança e cotas, indica uma conta verificada
como administrador inicial e só então pode liberá-la.
Cada mudança exige motivo e versão atual, ocorre em transação e entra em
`provider_audit`. A troca de dono do funil continua exigindo migração assistida.

Novas rotas: `POST /api/v1/admin/tenants/{id}/package`,
`POST /api/v1/admin/tenants/{id}/initial-admin` e
`POST /api/v1/admin/tenants/{id}/status`. A indicação inicial só funciona
enquanto a empresa não possui memberships; não concede ao provedor acesso
regular à gestão dos usuários. No produto, a empresa segue
administrando convites e memberships em `/licenses`, limitada pela cota de
licenças definida pelo provedor. A suspensão da empresa invalida a autenticação
de produto e a leitura direta via políticas RLS; o vencimento do ARES Connect
bloqueia as rotas de produto desse módulo. A degradação por cobrança continua
separada e preserva leitura, conforme a regra anterior.

Migration adicional: `20260927010000_provider_tenant_status_gate.sql`. Os preços
e prazos comerciais são informados por contrato; nenhum padrão comercial foi
inventado. Aplicar a migration no banco alvo antes de habilitar o painel novo.

Fontes: [plano de sprints, seção 3.6](https://app.notion.com/p/3c9e18aa7b0d810caecdc74de94dc34e),
[painel do provedor e licenciamento](https://app.notion.com/p/3c9e18aa7b0d8188803ee4804910bcd0)
e [modelo canônico](https://app.notion.com/p/3c9e18aa7b0d8138a606f0fd9f89278c).

Estado em 16/09/2026: as cinco partes planejadas estão implementadas e
verificadas localmente (API, banco, navegador). O que resta é externo ao
código: provisionar o operador real do provedor, ratificar a moeda das cotas,
chave OpenAI para o aceite do chat M5 e homologação do adapter do CRM real.

## 1. Painel e API de controle do provedor

- Identidade em `private.provider_operators`, fora das memberships de clientes.
  Nenhum admin de tenant é promovido automaticamente. Um operador ativo, conforme
  a especificação. Conta de provedor não pode ter membership, inclusive inativa.
- `ProviderSession` é um caminho de autenticação separado. GoTrue valida o token;
  a API confere o `session_id` em `auth.sessions`, validade e operador ativo no banco.
  Revogação é reavaliada em cada operação, sem confiar em `user_metadata`.
- `GET /api/v1/admin/tenants`: diretório administrativo com cursor UUID, até 100
  registros, sem conteúdo comercial. Leitura de cada tenant deixa auditoria.
- `GET /api/v1/admin/tenants/{id}`: configuração, módulos, cobrança e cotas, com
  auditoria de leitura.
- `POST /api/v1/admin/tenants`: cria tenant sem conceder automaticamente módulo,
  cota, licença ou acesso de usuário. Nome, slug e motivo obrigatórios.
- `POST /api/v1/admin/tenants/{id}/entitlements`: motivo e `expected_version`
  obrigatórios; bloqueio da linha de tenant serializa alterações. Retorna 409
  em versão obsoleta ou troca de dono de funil. A restrição permanece mesmo se
  o módulo anterior estiver suspenso/revogado: troca exige migração assistida.
- `POST /api/v1/admin/tenants/{id}/billing` e `.../quotas`: mesma disciplina de
  versão, bloqueio e auditoria (ver seções 2 e 3).
- `provider_audit` é separado da auditoria do produto e registra ator, motivo,
  timestamp, correlação, antes e depois. Atualização, exclusão e truncamento são
  recusados por trigger; papéis do produto não leem essa tabela nem alteram
  configuração. Alteração comercial e auditoria pertencem à mesma transação.
  Consequência prática: um tenant que já foi listado pelo provedor não pode mais
  ser apagado (`on delete restrict`), inclusive tenants sintéticos de teste.
- Tela `/admin` com login e `sessionStorage` próprios (`ares-provider-session`),
  fora do `AuthGate` do produto. A sessão do produto nunca é reaproveitada; o
  admin do produto recebe 403 e a mensagem orienta a usar a conta dedicada.

Migration: `20260915010000_m6_provider_foundation.sql`.

## 2. Cotas de IA, reservas concorrentes e reconciliação

Decisão de moeda: o contrato oficial define cotas e consumo em BRL; a
implementação M1/M5 mede custo em USD. Foi implementada a opção "contrato em
BRL com conversão configurável e auditada": `tenant_quotas` guarda
`usd_brl_rate` e `rate_source` obrigatórios; cada reserva congela a taxa vigente
(`ai_budget_reservations.usd_brl_rate`), e mudanças posteriores de taxa não
reescrevem consumo passado. A ratificação formal dessa escolha pelo responsável
ainda não está registrada; nenhum valor comercial, taxa de mercado ou prazo foi
inventado — o piloto local usa uma taxa explicitamente rotulada como sintética.

- `QuotaGuard.reserve` (em `ares/ai/quotas.py`) roda em `select ... for update`
  da linha de cota, soma consumo diário/mensal medido mais reservas pendentes e
  nega quando o estimado ultrapassa qualquer teto, quando a cota não existe
  (`quota_unconfigured`), quando o orçamento diário é zero, quando a cobrança está
  degradada (`billing_degraded`) ou quando o mesmo `run_id` já reservou.
  Reservas concorrentes não conseguem exceder o teto (teste com quatro threads).
- Aviso a partir de 80% do teto diário ou mensal, exposto em
  `GET /api/v1/account/quota` e no `QuotaNotice` da interface. Cota zerada é
  apresentada como bloqueio explícito, não como "80% do limite".
- `settle_on` reconcilia com o custo real: `settled` alimenta
  `tenant_usage_daily` (uma vez, idempotente); `not_called` libera a reserva;
  custo desconhecido mantém a reserva comprometendo saldo, inclusive entre
  períodos, por conservadorismo.
- Na primeira configuração de cota, o histórico USD do `ai_usage_ledger` vira
  saldo de abertura pela taxa informada, rotulado `opening-balance:` na
  reserva — não é uma cotação histórica.
- Chat M5 e Model Factory chamam `reserve` antes de qualquer modelo; negação cai
  no fallback determinístico já existente.

Migration: `20260916010000_m6_quotas_licenses.sql`.

## 3. Licenças, convites e cobrança

- `tenant_quotas.seats_limit` é o contrato de licenças. Convite pendente reserva
  uma licença; o limite é checado no convite, na ativação e por trigger
  (`membership_seat_guard`) mesmo em escrita direta via SQL ou Data API.
  Tenants sem cota configurada falham fechado (`seat_contract_unconfigured`).
- `GET /api/v1/account/licenses` (somente admin ativo do tenant) lista convites e
  membros com cursores. `POST /api/v1/account/invitations` registra o convite
  com motivo e não envia e-mail. `.../invitations/{id}/activate` exige conta
  GoTrue com e-mail verificado, não operador de provedor, e troca a reserva por
  membership ativa na mesma transação. `.../cancel` e `POST /memberships/{id}`
  exigem `expected_version`; o admin não altera a própria membership.
  Tudo auditado em `audit_log` com `source='ares:licenses'`.
- Cobrança em `tenant_billing_state`: `active`, `past_due` (com `due_since` e
  `grace_until`) e `degraded`. O provedor só pode marcar `degraded` após o
  prazo de tolerância vencer no fuso do tenant.
- Degradação preserva leitura e histórico: `require_user` recusa métodos de
  escrita com `billing_degraded` (403) e políticas RLS restritivas
  (`billing_insert_gate`/`update`/`delete`) aplicam a mesma regra a toda tabela
  com `tenant_id`, inclusive pelo Data API. Reserva de IA e resolução de lead
  também recusam. `GET /api/v1/account/billing` alimenta o `BillingNotice`.
- Suspensão de módulo continua sendo um mecanismo distinto do fluxo de cobrança.

Migrations: `20260915020000_m6_billing.sql`, `20260916010000_m6_quotas_licenses.sql`.

## 4. Entrada de leads e deduplicação humana

- `lead_intake` guarda a entrada com `idempotency_key` por tenant e
  `fingerprint` do payload: repetição idêntica devolve o mesmo registro;
  payload diferente com a mesma chave é 409. Sem escrita direta nem leitura
  ampla: vendedor vê apenas os próprios leads; admin e gestor veem o tenant.
  Exige módulo `ares_connect` ativo.
- Candidatos (`GET /leads/{id}/candidates`): similaridade de nome normalizado
  (≥ 0,75) e igualdade de e-mail ou telefone, com motivos explícitos e no máximo
  20 resultados entre os cadastros acessíveis ao usuário.
- Resolução humana (`POST /leads/{id}/resolve`): `create`, `merge`, `discard` e
  `undo`, sempre com motivo e `expected_version`. Mesclar registra
  `merge_operations`, preserva o original e permite desfazer. Criação vai ao CRM
  com chave idempotente `ares-lead:{tenant}:{lead}`; falha na chamada deixa o
  lead `uncertain` e a única saída é repetir a mesma intenção. Um advisory lock
  por tenant impede duas escritas simultâneas.
- Só responde em `development` com o FakeCRM (`client_crm_adapter_not_configured`
  fora disso). O sandbox ganhou `POST /v1/leads`; a `bridge` local (porta 8011)
  preserva um sandbox M4 já em execução e dá durabilidade SQLite aos leads.

Migration: `20260915030000_m6_lead_intake.sql`.

## 5. Impacto ARES, exportação e ensaio de piloto

- `GET /api/v1/impact/summary?days=` (1–365) em transação `repeatable read`
  somente leitura: em risco, trabalhadas, último outcome por oportunidade
  agrupado por moeda, contagem de observações sintéticas, custo de IA medido.
  Definições e limitações fazem parte da resposta; incremental só aparece com
  `attribution_level='incremental_proven'` e método registrado — senão é
  "Não comprovado", nunca zero. Ausência de outcome não é receita zero.
- `GET /api/v1/impact/interventions` pagina a trilha com o último outcome de
  cada intervenção e link para a oportunidade.
- `GET /api/v1/reports/impact/export?format=csv|pdf`: até 500 linhas responde
  na hora; acima disso enfileira em `report_exports` (payload expira em 1 h,
  `GET /reports/exports/{id}` com 202 enquanto processa). Toda exportação
  audita `report.export`. CSV escapa fórmulas; PDF via reportlab. Relatórios com
  dados sintéticos carregam o aviso no arquivo e na tela.
- `scripts/bootstrap-m6-local.py` monta o piloto sintético local: operador
  `provider-m6@ares.local` (credencial em `output/runtime`, ignorado pelo Git),
  três outcomes rotulados `[SINTETICO M6]` (observado, influenciado, não
  comprovado) e cota de 10 licenças com orçamento de IA zero. Só roda com
  Supabase e banco em `localhost`.

Migration: `20260915040000_m6_report_exports.sql`.

## Verificação em 16/09/2026

- Backend com banco local (`ARES_TEST_DATABASE_URL`): **138 passaram, 0 falhas**,
  incluindo os 25 testes de integração de provedor, cobrança, cotas, licenças,
  leads e impacto. As duas falhas registradas em 15/09 (`producer` restrito ao
  literal `fake-crm`; fixture M2 com identificador fixo) foram corrigidas.
  Ruff, formatação e mypy sem erros.
- Frontend: **57 testes** (19 novos para `/admin`, `/licenses`, `/leads` e
  `/impact`), typecheck e build passaram. Lint só com avisos de Fast Refresh.
  `format:check` continua falhando em 31 arquivos anteriores ao M6, não
  tocados nesta entrega.
- Ensaio real no navegador (`apps/web/scripts/verify-m6-live.cjs`, sem
  interceptação): convite reservado e cancelado; lead criado no CRM local;
  mesclagem humana e desfazer; CSV e PDF reais com aviso sintético; login real
  do operador dedicado e leitura da configuração. Quatro rotas em 1440/700/390
  px sem overflow, sem violações axe (WCAG 2.1 AA) e com foco de teclado.
  Evidências em `output/playwright/m6-live/` (`report.json`, screenshots,
  vídeos, `impact.csv`, `impact.pdf`).
- Ensaio do painel do provedor (`verify-m6-provider.cjs`): 403 real para o
  admin do produto, armazenamento de sessão independente, diretório/conflito
  409/exclusão de funil com respostas sintéticas interceptadas, seis
  combinações claro/escuro × largura, teclado e axe sem violações.
- Correções feitas nesta rodada: seletor obsoleto no ensaio ao vivo
  (`.provider-directory` → `.provider-tenants`) e rótulo ambíguo no ensaio do
  provedor; tabela de Impacto rolável agora é região focável (violação
  `scrollable-region-focusable` a 390 px); BOM removido de `ImpactPage.tsx`;
  editor de cobrança abre no estado atual; editor de cotas confirma sucesso;
  aviso de cota zerada; duas linhas longas em testes.

Reprodução:

```powershell
npm run dev                      # API 8000, web 5173, sandbox 8010, worker
python -m uvicorn ares.fake_crm_sandbox.bridge:app --port 8011   # opcional, ver seção 4
python scripts/bootstrap-m6-local.py
npm run test:e2e:m6 --workspace @ares/web
npm run test:e2e:m6:provider --workspace @ares/web
```

## Pendências fora do código

1. Provisionar e ensaiar a recuperação do operador real do provedor
   ([m6-provider-recovery.md](m6-provider-recovery.md)); nenhuma conta real existe.
2. Ratificar a moeda das cotas (seção 2) e definir taxa, fonte e valores
   comerciais reais. Nada disso foi inventado.
3. Aceite real do chat M5 depende de chave OpenAI no backend.
4. Leads, sync e write-back seguem sobre o FakeCRM; o adapter do CRM real do
   cliente continua sem homologação.
5. O banco local acumula quatro tenants `Synthetic quota test` de uma rodada de
   testes anterior ao teardown atual; como já foram auditados pelo provedor,
   só saem com `npm run db:reset`. Nenhum dado foi apagado nesta entrega.
