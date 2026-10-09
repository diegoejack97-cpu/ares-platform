# Auditoria local de segurança — ARES — 07/10/2026

> Atualização: as correções autorizadas após esta auditoria estão registradas em
> [Correções de segurança](security-hardening-2026-10-07.md). Os achados e resultados
> abaixo preservam o diagnóstico anterior às alterações.

## Parecer

**Não considero encerrada a preparação de segurança para abrir o SaaS ao público.** Foi reproduzida uma inconsistência de autorização de leitura: um vendedor limitado à própria oportunidade no Command Center consegue ler outras oportunidades da mesma empresa pelo Radar, pelo detalhe da API e pela leitura direta do banco como `authenticated`.

Não foi demonstrado acesso entre empresas nos testes executados. Isso não constitui certificação nem prova de ausência de outras falhas. Uma apresentação assistida com dados sintéticos continua tendo escopo diferente de uma publicação com dados de clientes.

Prioridade: corrigir o achado 001, atualizar as dependências afetadas e validar limites de requisição na publicação. As proteções de decisões e execução no CRM passaram nos testes existentes, mas esses testes não cobriam a diferença de leitura encontrada nesta auditoria.

## Escopo e método

- Código de referência: `896d6b40ffb6ecab9f4ea903ddef1729ef3659f2`, branch `feat/visual-system-v2`.
- Revisão local de FastAPI/Python, React/TypeScript, autenticação, permissões, CRMProvider, chat, migrations/RLS, Docker/Caddy e CI. Busca inicial no grafo local, seguida de inspeção das implementações relevantes. Atualização final do grafo somente por AST, sem extração semântica externa.
- `npm audit` no lockfile instalado; `pip-audit 2.10.1` sobre os metadados da `.venv`, instalado em ambiente separado em `output`. Foram consultados nomes/versões de pacotes em bases públicas de vulnerabilidades; código e credenciais não foram enviados.
- Testes em memória e PostgreSQL **descartável**, `ares_test_mvp_20261005`, porta 56422. Os novos exemplos de autorização usaram dados sintéticos em transação revertida. Nenhuma ação em CRM real ou no banco principal. O container descartável foi parado ao final, preservando o volume.
- Comparação local de segredos configurados e padrões limitados de credenciais contra arquivos rastreados e o bundle já existente. Valores não aparecem nos relatórios.
- Nenhuma correção no código de produto, migration, dependência ou configuração de produção foi aplicada nesta tarefa. A alteração anterior do usuário em `.agents/skills/ares-visual-identity/SKILL.md` foi preservada.

### Strix

Instaladas as nove skills oficiais do [Strix](https://github.com/usestrix/strix), revisionadas em `f1386cad37964197a483ff43c25161f9d933f050`, no diretório pessoal de skills. O pacote CLI `strix-agent 1.7.0` também está instalado em ambiente separado; a versão foi confirmada por metadados. O launcher Windows apresentou acesso negado, e sua execução não foi validada.

**Nenhuma varredura Strix foi iniciada.** A revisão automática rejeitou a execução proposta por envolver envio de uma cópia do código privado à OpenAI usando a chave existente. Após explicação e pergunta explícita, o usuário escolheu **“Manter somente auditoria local, sem enviar código”**. Essa escolha foi respeitada; não houve tentativa de contornar o bloqueio por CLI alternativa, cloud ou outro provedor.

A cópia limpa de 373 arquivos ficou somente em `output/security-2026-10-07/ares-target`, sem `.env`, `.git`, credenciais ou dados locais. Não foi enviada. Não existem resultados de pentest Strix que fundamentem este parecer.

## Achado de prioridade alta

### 001 — Escopo de vendedor inconsistente entre Command Center, Radar e RLS

**Estado:** reprodução local confirmada. **Impacto:** leitura de títulos, valores, evidências e detalhes de oportunidades da mesma empresa fora do recorte de propriedade aplicado no Command Center. Não foi demonstrada escrita indevida nem acesso entre empresas.

Evidências:

- `docs/command-center.md:22` define o recorte próprio do vendedor; `backend/tests/test_postgres_command_center.py:339` verifica esse contrato.
- `backend/src/ares/api/app.py:539` aceita `owner` da consulta e o repassa à listagem sem obrigar o ID do vendedor autenticado. A ausência desse filtro amplia a população.
- `backend/src/ares/intelligence/service.py:470` começa a seleção apenas com `tenant_id`; o filtro de proprietário é opcional.
- `backend/src/ares/api/app.py:567` e `backend/src/ares/intelligence/service.py:631` entregam detalhes por tenant + ID sem autorização de proprietário antes da leitura. Contexto e analytics devem ser revisados junto: `app.py:678` e `app.py:431`.
- A policy genérica em `supabase/migrations/20260902021751_m1_completion_auth_worker_budget.sql:53` verifica membership/tenant, sem impor proprietário da oportunidade. O catálogo e a consulta como `authenticated` confirmaram o comportamento.

Reprodução: `output/security-2026-10-07/seller-read-probe.py`. A identidade autenticada de vendedor foi injetada no TestClient para isolar **autorização**, sem testar login nem falsificação de JWT. O fixture cria membership legítima e quatro oportunidades sintéticas. A transação é revertida ao final.

| Leitura com o mesmo vendedor | Resultado |
| --- | --- |
| Command Center | 1 oportunidade própria |
| `GET /api/v1/opportunities` | HTTP 200, 4 oportunidades |
| Registros fora da propriedade do vendedor | 3, sem responsável no fixture |
| Detalhe de uma oportunidade sem responsável | HTTP 200 |
| SELECT em `ares_opportunities` como `authenticated` | 4 registros |

Correção proposta: formalizar no contrato oficial se o vendedor pode ler toda a empresa ou somente sua carteira. A documentação executável atual tem recortes diferentes; não resolver essa divergência silenciosamente. Se o recorte próprio for a regra, centralizar autorização de leitura em lista/detalhe/contexto/analytics e aplicar o equivalente nas policies da Data API e evidências associadas. Um filtro visual ou corrigir somente o endpoint não fecha o acesso direto pelo Supabase.

Aceite: vendedor vê somente os registros permitidos em todas as superfícies, não amplia acesso omitindo/trocando `owner`, recebe 404/403 no detalhe fora de escopo, e continua sem acesso a outro tenant. Gestor/admin/auditor mantêm o acesso definido pelo produto. Adicionar regressões específicas: os testes existentes passaram sem detectar esta diferença.

## Dependências — avisos confirmados, exploração no ARES não demonstrada

### 002 — Cinco avisos distintos exigem atualização e verificação contínua

O `npm audit` informou **três pacotes afetados**: dois marcados críticos e um alto. Isso corresponde a **dois avisos**, pois `concurrently` herda o alerta de `shell-quote`. Não são três falhas independentes da aplicação publicada.

O `pip-audit` avaliou 62 entradas: uma, o pacote local `ares-platform-backend`, não existe no PyPI e foi ignorada. Informou cinco ocorrências em três pacotes, mas `pip` e `pytest` aparecem duplicados com os mesmos IDs: são **três avisos distintos**. A revisão do código local cobre parcialmente o pacote ignorado, não é substituída pela base de dependências.

| Dependência instalada | Aviso / severidade do fornecedor | Versão corrigida | Aplicabilidade observada |
| --- | --- | --- | --- |
| `shell-quote 1.9.0`, via `concurrently 10.0.5` | [GHSA-pqg4-j6r4-53mv](https://github.com/advisories/GHSA-pqg4-j6r4-53mv), crítico | 1.11.0 | Ferramenta de desenvolvimento. Exploração depende de tokens específicos de comentário e quebra de linha chegando a `quote()` e depois a um shell. Os comandos do ARES são fixos; nenhuma entrada da API/chat foi ligada a esse caminho. |
| `source-map-js 1.2.1` | [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q), alto | 1.2.2 | Vite/PostCSS/Tailwind e jsdom. Source maps maliciosos podem bloquear processamento; nenhuma função da aplicação publicada recebe mapas de usuário. Apesar de Tailwind estar em `dependencies`, seu uso identificado é no build. |
| `pydantic-settings 2.13.1` | [GHSA-4xgf-cpjx-pc3j](https://github.com/advisories/GHSA-4xgf-cpjx-pc3j), moderado | 2.14.2 | Dependência de runtime. O caminho vulnerável exige `NestedSecretsSettingsSource`, subdiretórios e influência sobre symlinks. O ARES não usa essa fonte/opção; a pré-condição não foi encontrada. |
| `pip 26.1.2` na `.venv` | [GHSA-qwm4-qh6w-59xr](https://github.com/advisories/GHSA-qwm4-qh6w-59xr), moderado | 26.2.0 | Instalador; depende de índice de pacotes malicioso. Não é endpoint web. A versão do pip da imagem publicada não foi inventariada nesta auditoria. |
| `pytest 9.0.2` | [GHSA-6w46-j5rx-g56g](https://github.com/advisories/GHSA-6w46-j5rx-g56g), moderado | 9.0.3 | Ferramenta de testes, risco de diretório temporário em UNIX compartilhado. A exceção de permissão observada no Windows não demonstra exploração deste aviso. |

Fontes locais: `package.json:43`, `package-lock.json:7797`, `package-lock.json:7817`, `backend/pyproject.toml:16`, `backend/pyproject.toml:25`. Árvore verificada com `npm ls shell-quote source-map-js concurrently --all`.

Correção proposta: atualizar a resolução de `source-map-js`, atualizar/substituir a cadeia de `concurrently` ou usar override revisado de `shell-quote`, e atualizar as versões Python indicadas com testes de compatibilidade. Não executar `npm audit fix --force` indiscriminadamente: a sugestão automática inclui downgrade de `concurrently`. Inventariar também a imagem final de backend e seu instalador.

`.github/workflows/ci.yml:13` executa qualidade e banco, mas não tem auditoria de dependências. Adicionar verificação SCA e atualização periódica; uma auditoria antiga com zero alertas não continua válida depois da publicação de novos avisos. Os avisos citados foram consultados em 07/10/2026.

## Melhorias de proteção antes da abertura pública

### 003 — CSP ausente na configuração de publicação

**Prioridade média; defesa adicional, sem XSS demonstrado.** `deploy/Caddyfile:3` configura `nosniff`, proteção de frame, referrer e permissões, mas não Content Security Policy. O cliente Supabase é criado em `apps/web/src/lib/supabase.ts:10`; a sessão é acessível ao código do navegador. Uma futura falha de XSS teria impacto significativo.

O renderer de chat em `apps/web/src/features/chat/ChatMarkdown.tsx:9` bloqueia HTML, imagens e protocolos executáveis. Não foi encontrado uso de `dangerouslySetInnerHTML` ou `rehypeRaw` nos fontes revisados. Esses controles reduzem o risco; ausência de CSP não prova XSS.

Proposta: testar uma política inicialmente em report-only, restringir scripts ao necessário e definir conexões para a API/Supabase. Validar login, refresh de sessão, chat, gráficos e exports antes de enforcement. Conferir o header na resposta da implantação real, não apenas neste arquivo.

### 004 — Corpo do webhook lido integralmente antes da rejeição

**Prioridade baixa a média de disponibilidade; leitura confirmada, DoS não executado.** `backend/src/ares/api/app.py:245` faz `await request.body()` antes de resolver conexão e validar assinatura. `deploy/Caddyfile:11` não define limite de corpo; não foi encontrado limite equivalente no app revisado.

Uma única requisição de 1 MiB sem assinatura foi testada somente no TestClient com adapter em memória. Retornou 401, mas o corpo inteiro foi consumido antes da rejeição. Isso comprova a ordem e o buffer; não comprova queda de produção nem seu limite de memória. O caminho PostgreSQL passa pela mesma linha, mas não foi submetido a teste de carga.

Proposta: limite de bytes no proxy e na leitura streaming, incluindo requests sem Content-Length/chunked; rejeitar assinatura ausente antes de ler e validar a conexão antes de processar o payload. Definir tamanho pelo contrato do CRM. Acrescentar throttling para tráfego público e chamadas caras sem prejudicar webhooks legítimos. Quota de IA não substitui limite de tráfego.

Evidência: `output/security-2026-10-07/local-probes.json`, `bytes_buffered_before_rejection=1048576`.

### 005 — Event Journal sem paginação ou limite de consulta

**Prioridade baixa, exposição autenticada a consumo crescente.** `backend/src/ares/event_journal/service.py:169` ordena todos os eventos do tenant e chama `fetchall()` em `:172`; `app.py:258` publica a coleção. Não há limite/cursor ou timeout de SQL nessa leitura.

Com o aumento do histórico, uma única consulta materializa e serializa todo o journal. Não foi feito teste de carga nem demonstrada indisponibilidade. Proposta: paginação por data + ID, teto de página, janela/filtros e timeout; revisar payloads e escopo por papel junto ao achado 001.

### 006 — OpenAPI continua registrada fora da configuração explícita de docs

**Prioridade baixa e condicionada à forma de implantação.** `backend/src/ares/api/app.py:79` desabilita `/docs` fora de desenvolvimento, mas não configura `openapi_url=None`. A construção atual mantém `/openapi.json`.

No Compose revisado a API não publica porta própria (`deploy/compose.yaml:57`) e o Caddy encaminha somente `/api/*` e `/health/*`; portanto não foi demonstrada exposição pública do schema nessa topologia. Se o backend for publicado diretamente, a proteção do edge deixa de existir. Proposta: desligar o schema fora de desenvolvimento ou protegê-lo explicitamente. Isso não equivale a vazamento de credenciais.

### 007 — Ajustes preventivos no catálogo de banco

**Prioridade baixa; não houve acesso anônimo a dados demonstrado.** Das 58 tabelas públicas no banco descartável, 57 têm RLS. `sentinel_scan_runs` não tem RLS, porém `anon` e `authenticated` não possuem SELECT. Não foram encontrados views públicos.

`public.can_access_tenant` é SECURITY DEFINER com search_path vazio e tem EXECUTE para `anon`; foi recriada em `supabase/migrations/20260927010000_provider_tenant_status_gate.sql:21`. A função verifica tenant e membership do usuário, portanto poder invocá-la não demonstra acesso indevido. Proposta: adicionar RLS como defesa adicional à tabela interna e revogar execução anônima desnecessária da função; manter revisão de grants e policies no CI.

Evidência: `output/security-2026-10-07/database-inventory.json`. O achado 001 mostra por que RLS habilitada, sozinha, não garante o escopo de vendedor.

## Verificações executadas

| Verificação | Resultado e limite |
| --- | --- |
| Backend sem integração | 178 passaram; 2 erros de setup por permissão no diretório temporário Windows. Os 2 passaram em nova pasta isolada, sem mudar o código. |
| Backend PostgreSQL | 82 passaram, incluindo isolamento de tenant, roles, revogação, quotas, plano, decisões, idempotência, chat privado e roteamento por empresa. |
| Frontend | 96 de 97 passaram no lote paralelo. A falha de paginação do Radar foi repetida isoladamente: 2 de 2 testes do arquivo passaram. O lote inicial não foi declarado integralmente verde. |
| Acesso anônimo | 64 combinações de rota/método sob `/api` retornaram 401 no TestClient; webhook foi verificado separadamente. Isso não testa todos os casos de token autenticado ou o edge de produção. |
| Escopo de vendedor | Inconsistência reproduzida conforme achado 001. |
| Segredos | Zero correspondências suspeitas em 427 arquivos rastreados atuais e 50 arquivos do bundle existente, após excluir chaves públicas/publishable. Scan limitado a valores configurados e padrões; histórico Git não auditado. |
| Catálogo SQL | 58 tabelas públicas; 1 sem RLS e sem SELECT público; 1 função pública definer; nenhum view público. |

Artefatos em `output/security-2026-10-07/`: relatórios JSON de dependências, XMLs de testes, `frontend-tests.json`, probes e inventário. Diretório ignorado pelo Git. O relatório presente é revisável e versionável; os artefatos não foram publicados.

## Cobertura restante e sequência recomendada

1. Alinhar a regra global de leitura por vendedor com o Notion e fechar o achado 001 no backend e na Data API; verificar todos os fluxos que retornam evidências/contexto.
2. Atualizar dependências afetadas, reconstruir as imagens, executar qualidade/regressões e repetir SCA contra os ambientes finais. Incluir gates de dependências no CI.
3. Configurar e testar limites de requisição, throttling, CSP e paginação do journal na topologia que será publicada.
4. Validar a implantação real: configuração de Supabase Auth, expiração/revogação de sessão, rate limits, grants efetivos, MFA do operador da plataforma, recuperação de conta, backups e restauração. Não houve teste de GoTrue real ou navegador nesta rodada; Auth foi verificado por testes existentes/mocks e leitura de código.
5. Homologar adapter, credenciais por empresa, mapeamento, sincronização, reconciliação, webhook e write-back com o CRM real antes de usar dados de clientes. A auditoria local não substitui essa etapa.

Não foram executados: Strix, envio do código a modelo externo, pentest externo, stress/DoS, exploração em produção, revisão completa do histórico Git, scanner de imagens Docker, validação de configuração do cloud/Supabase hospedado ou teste com CRM real. SQL injection, SSRF, prompt injection e XSS foram inspecionados nos caminhos selecionados, sem campanha completa de exploração. Não afirmar ausência dessas classes com base neste relatório.

Este parecer registra as evidências anteriores às correções. Consulte o documento de correções para o estado de validação atual; nenhum dos dois constitui aprovação geral de segurança do SaaS.
