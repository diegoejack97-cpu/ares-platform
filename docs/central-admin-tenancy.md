# Central Admin e isolamento entre empresas

## Papéis e telas

`/central-admin` é a área do operador do provedor. Ela exige uma conta dedicada
em `private.provider_operators` e sessão válida; uma conta de administrador de
empresa não recebe esse acesso. O operador configura empresas, pacote,
vencimento, cobrança, licenças, orçamento de IA e capacidade contratada para
agentes e sentinelas. O detalhe mostra consumo e ocupação da empresa
selecionada, sem expor negócios ou dados comerciais dela.

`/licenses` é a gestão de membros e convites da própria empresa, acessível ao
administrador do tenant pelo item **Usuários e licenças** no menu do ARES.
`/command-center` continua no mesmo menu como visão operacional dos negócios
da empresa, com escopo conforme o papel do usuário. Ele não substitui a gestão
de usuários nem o painel do provedor: são três responsabilidades distintas.

Os limites `agent_slots` e `sentinel_slots` representam capacidade de rotinas
ativas, não número de execuções mensais. Hoje há uma rotina de agente
(`follow-up+triage`) e uma regra de sentinela (`SENTINEL-SLA-OVERDUE`). Zero
bloqueia a rotina no backend. Capacidade maior que um fica reservada para um
catálogo futuro; ela não cria rotinas extras. A métrica de execuções no painel
inclui chamadas de IA registradas e não deve ser confundida com agentes ativos.

## Isolamento SaaS

Cada empresa recebe um `tenant_id`; a sessão Auth seleciona o tenant ativo em
`app_metadata`, e o backend exige membro ativo antes de atender chamadas do
produto. Dados de negócio carregam `tenant_id`; consultas e políticas RLS
restringem cada conta ao seu tenant. Conexões e eventos de webhook também
carregam `tenant_id` e `connection_id`. Credenciais de CRM devem permanecer no
backend, associadas à conexão da empresa e selecionadas a partir do contexto
autenticado, nunca de um identificador livre enviado pelo navegador.

Essa é a separação de identidade e dados já estabelecida no ARES. A integração
multiempresa com CRMs reais ainda **não está pronta**: o fluxo de sincronização
e write-back usa o FakeCRM e configurações globais do ambiente de
desenvolvimento; fora dele, algumas rotas recusam o adapter do cliente. Para
atender várias empresas com CRMs distintos, faltam o registro de adapters e
segredos por conexão, seleção do provider por `tenant_id`/`connection_id`,
roteamento autenticado de webhooks, política de troca de CRM e testes cruzados
com dois tenants. Nenhuma empresa deve ser liberada para integração real antes
dessas verificações.

Referência normativa: [Ecossistema NOGUEIRA!IA — Pacotes, Painel do Provedor e
Regras de Licenciamento](https://app.notion.com/p/3c9e18aa7b0d8188803ee4804910bcd0).
