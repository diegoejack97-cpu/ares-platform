# Correções de segurança — 07/10/2026

Implementação autorizada após a [auditoria local](security-audit-2026-10-07.md).
O código permaneceu local: Strix e envio do repositório a modelos externos não foram executados.

## Correções implementadas

| Achado | Correção |
| --- | --- |
| 001 — Carteira do vendedor | API de Radar, analytics, detalhe, contexto, grafo e achados dos sentinelas passam a respeitar a propriedade. As leituras interativas de oportunidades/contextos/journal usam RLS com identidade verificada pelo servidor. Policies restritivas cobrem oportunidades, evidências, recomendações, decisões, execução, eventos e vínculos indiretos. Membership, empresa ativa e plano vigente são verificados no banco, inclusive para um papel em cache. |
| 002 — Dependências | `shell-quote` 1.11.0, `source-map-js` 1.2.2, `pydantic-settings` 2.14.2, `pytest` 9.0.3 e `pip` 26.2.0. Lockfile atualizado e SCA npm/Python incluído no CI. |
| 003 — CSP | Caddy aplica política com scripts locais, origem explícita do Supabase, bloqueio de frames/objetos e restrição de base/formulários. Estilos inline permanecem permitidos para os componentes e gráficos. |
| 004 — Corpo/webhook | Teto de 1.048.576 bytes no ASGI e Caddy, inclusive chunked. Assinatura ausente/malformada rejeitada antes da leitura. Conexão PostgreSQL é resolvida antes de consumir o corpo. Guarda de tráfego anterior à autenticação. |
| 005 — Event Journal | Cursor por `recorded_at` + UUID, página padrão 50/teto 100, timeout SQL de 5 s, índice correspondente e contador restrito ao acesso. Interface com Anterior/Próxima; gráfico explicitamente identificado como recorte da página. Fontes internas e eventos sem ID do provedor são aceitos no contrato. |
| 006 — OpenAPI | Schema e documentação são registrados apenas em desenvolvimento. |
| 007 — Catálogo | RLS ativada em `sentinel_scan_runs`, sem acesso do navegador. Execução anônima de `public.can_access_tenant` revogada. Contadores de tráfego ficam em schema privado, com RLS e sem grants públicos. |

A regra de leitura segue o [contrato oficial de UX/RBAC](https://app.notion.com/p/3c3e18aa7b0d81acb2dbf39cbbc334b9): vendedor na própria carteira; administrador, gestor e auditor no recorte autorizado da empresa. Os negócios canônicos continuam API-only, sem novo SELECT público na tabela `deals`. O join da API usa a visão não exposta `private.portfolio_deals`, com barreira de segurança e predicado obrigatório de acesso por linha. Workers internos continuam com suas leituras próprias.

## Rate limit por usuário

| Configuração | Padrão | Escopo |
| --- | --- | --- |
| `ARES_RATE_LIMIT_REQUESTS_PER_MINUTE` | 120 | Todas as requisições autenticadas |
| `ARES_RATE_LIMIT_WRITES_PER_MINUTE` | 20 | POST/PUT/PATCH e demais mutações |
| `ARES_RATE_LIMIT_CHAT_PER_MINUTE` | 6 | POST do chat, além dos limites anteriores |
| `ARES_RATE_LIMIT_IP_PER_MINUTE` | 600 | Guarda por peer ASGI antes da autenticação; por processo |

São token buckets: cada limite permite um pico de até sua capacidade e repõe tokens progressivamente durante o minuto. A chave persistida deriva de usuário + empresa; renovar o token, abrir outra aba ou entrar novamente não cria um novo contador. O operador da Central Admin tem namespace próprio. Em PostgreSQL, bloqueios de linha tornam o consumo atômico entre processos/instâncias. O modo em memória existe apenas para testes/desenvolvimento. Contadores inativos há mais de um dia são removidos em lotes limitados; não armazenam JWT, e-mail ou IP em claro.

Excesso retorna HTTP 429 com `Retry-After`, correlação e `Cache-Control: no-store`. O chat explica o tempo de espera. Falha do banco do limitador bloqueia a chamada com 503; não desativa silenciosamente a proteção. Isso controla requisições da sessão autenticada e não altera sua duração, o timeout de inatividade ou as quotas de IA.

A guarda pré-auth usa somente o peer fornecido pelo ASGI e ignora headers encaminhados não confiáveis. Atrás do proxy, confirme quais IPs Uvicorn aceita como proxy confiável: sem essa configuração, o peer pode ser o próprio Caddy, compartilhando o limite entre clientes. Ajuste o teto para o tráfego esperado. Para publicação com múltiplas réplicas, complemente o tráfego público com um limitador compartilhado no edge. Os limites de login do GoTrue/Supabase e MFA continuam configurações do ambiente hospedado.

## Banco e publicação

A migration é `20261007151537_security_read_scope_and_limits.sql`, a 22ª do projeto. Foi aplicada primeiro ao PostgreSQL descartável e depois, em transação, ao Supabase local de desenvolvimento, sem reset nem exclusão de dados. API e worker locais foram reiniciados após essa aplicação. Não foi aplicada a uma base cloud.

Antes de publicar: aplicar as 22 migrations na base de destino e reconstruir os serviços. O usuário PostgreSQL do backend precisa assumir `authenticated` nas transações de leitura, além de suas permissões internas de worker. O ambiente atual usa o papel de servidor já previsto pelo projeto; não usar credencial do navegador como conexão do backend. A origem em `ARES_SUPABASE_URL` do serviço web deve corresponder à URL pública do Supabase usada no build. WebSocket externo permanece bloqueado; uma futura adoção de Realtime deve acrescentar sua origem explícita à CSP.

## Evidências de validação

- 188 testes backend sem integração passaram.
- 86 testes PostgreSQL passaram, incluindo carteira própria, filtros sem ampliação de acesso, papel desatualizado, membership revogada, RLS dos dados relacionados, paginação sem repetição e limite concorrente entre instâncias.
- 99 testes frontend e 56 contratos pgTAP passaram. Typecheck e build de produção passaram; imagens backend/web foram reconstruídas.
- `npm audit`: zero alertas conhecidos depois das atualizações. `pip-audit` da `.venv` e das 51 dependências públicas da imagem backend reconstruída: zero alertas conhecidos; o pacote privado ARES é analisado pelo código/testes, não pela base pública de advisories.
- Ruff, formatação backend, mypy e formatação frontend passaram. O lint frontend conserva nove avisos anteriores, sem erros.
- Containers isolados: readiness 200, configuração Caddy válida, CSP e headers efetivamente servidos pelo proxy, corpo acima de 1 MB rejeitado com 413 (Content-Length e chunked no webhook) e `/openapi.json`, `/docs`, `/redoc` retornando 404 diretamente na API de demonstração.
- Navegador conectado à API/PostgreSQL dos containers: duas páginas de 50 eventos, sem repetição; Anterior/Próxima por teclado. Desktop 1440 px, tablet 820 px e celular 390 px sem transbordamento horizontal após as transições. Capturas inspecionadas; nenhum erro de console no fluxo com a API real. Estados vazio e erro verificados com respostas controladas no navegador.
- Varredura local de 427 arquivos versionados, 11 arquivos novos e 50 arquivos do bundle: nenhuma ocorrência dos segredos configurados ou padrões de credenciais pesquisados. A checagem não cobre histórico Git nem todos os formatos possíveis de segredo.

Artefatos de execução, credenciais sintéticas e capturas permanecem em `output/` ou no diretório local ignorado do CLI do navegador. A alteração anterior na skill de identidade visual foi preservada.

## Limites do parecer

Estas correções fecham os problemas identificados no código dentro do escopo verificado. Antes de atender dados de clientes, ainda são necessárias a homologação do CRM real e a verificação da implantação hospedada: Auth, revogação/expiração de sessão, MFA do operador, recuperação de conta, TLS, limites do edge, backups/restauração e grants efetivamente implantados. Não houve pentest externo nem teste de carga/DoS. SCA sem alertas conhecidos não comprova ausência de vulnerabilidades.
