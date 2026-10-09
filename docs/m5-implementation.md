# M5 — execução iniciada em 12/09/2026

## Baseline

O [plano 16](https://app.notion.com/p/3c9e18aa7b0d810caecdc74de94dc34e)
define chat com streaming, ferramentas visíveis e contexto; grafo determinístico
com proveniência; visualização acessível; tela de agentes.
Memória semântica está fora deste recorte.

O [aceite específico da M4](https://app.notion.com/p/3d6e18aa7b0d81b989f4ffbb37d7b9ee)
confirma a conclusão local. Os avisos gerais de 04/09 ainda descrevem o estado
anterior; a homologação do CRM do cliente continua pendente. Não há declaração
de aceite real da M4 nem encerramento da M5.

## Primeira entrega: API de transparência

`GET /api/v1/agents?days=30` consulta os runs do tenant autenticado.
A janela aceita 1–90 dias e usa início inclusivo e fim exclusivo.
Agrupa por nome, versão, modo de geração e modelo; informa contagens por estado,
última execução, quantidade de amostras e p95 da duração registrada do run.
Runs sem término, ainda em execução ou com duração negativa não entram no p95.
Esse tempo não é a latência isolada do provedor do modelo.

A leitura exige admin, gestor ou auditor, membership ativa, tenant ativo e
licença ARES Connect ativa e não expirada, conferidos na mesma transação de
leitura das métricas. Vendedores são bloqueados. As queries usam tenant explícito.
Falhas do banco retornam mensagem segura e código de correlação.

M3 registra Follow-up e Triagem juntos: a API preserva `follow-up+triage`, sem
inventar runs independentes. `proposal_only` descreve a geração da recomendação;
as ações continuam sujeitas à Policy e ao worker, incluindo notas autorizáveis.

**Lacuna encontrada:** custo e tokens da M3 têm defaults zero, mas a geração não
persiste medição de uso. `cost_usd=null` e `cost_status=not_instrumented` tornam essa
ausência explícita, inclusive no fallback: uma chamada que falhou pode ter custo.
Não somar os zeros históricos como se fossem custo medido.

Nenhuma migration, escrita no CRM ou chamada de modelo é necessária para esta API.
## Segunda entrega: tela de Agentes

Rota `/agentes` disponível no menu. Consulta a API real, com filtros de 7, 30 e
90 dias, atualização manual e periódica, versão, modo de geração, estados,
última execução, p95 e custo explicitamente ausente. Uma resposta 401/403 oculta
dados anteriores; erro transitório preserva a última leitura com aviso de frescor.
Cache separado por usuário, tenant e período. Não há chamada de modelo ao abrir a tela.

Direção visual: superfície contínua do Observatório, grafite/marfim/cobre e Archivo
existentes; números tabulares, bordas e cantos dos tokens atuais. Métricas em faixa
no desktop e lista vertical no celular. Sem animação simulando atividade de agente;
skeleton respeita redução de movimento. A lista semântica é a própria alternativa
acessível, sem adicionar um gráfico que repetiria os mesmos números.

Contrato TypeScript gerado dos modelos OpenAPI com
`.venv/Scripts/python.exe scripts/generate-agent-contract.py`, seguido de Prettier
em `apps/web/src/features/agents/contract.ts`. Sem nova dependência.

## Verificação

- `backend/tests/test_agents.py`: autenticação, papel, janela e falhas sem vazamento.
- `backend/tests/test_postgres_agents.py`: SQL real, isolamento, p95, modos separados,
  janela, custo ausente, expiração e suspensão. Fixtures sintéticas com rollback.
- Lint, formatação e tipos pelo Python de `.venv`; suíte geral de backend.
- Frontend: 35 testes aprovados; lint sem erros (avisos Fast Refresh preexistentes),
  typecheck e build aprovados. API: 7 testes e tipos aprovados após explicitar o schema.
- Chrome real, API e PostgreSQL locais: 23 execuções existentes consultadas,
  sem seed, reset, mutação no CRM ou chamada de modelo.
- 10 combinações: claro/escuro em 1920, 1440, 1280, 820 e 390 px. Sem overflow,
  erros JavaScript ou violações axe detectadas. Capturas desktop/mobile inspecionadas.
- Teclado com foco visível no período e atualização; estados vazio e acesso negado
  simulados somente na camada de resposta do navegador; retry volta à API real.
- Script: `node apps/web/scripts/verify-m5-agents.cjs`. Artefatos ignorados pelo Git:
  `output/playwright/m5-agents/report.json` e capturas PNG. Aviso preexistente de
  bundle principal acima de 500 kB; a nova rota carrega sob demanda.

## Terceira entrega: grafo com evidências — 14/09/2026

Migration `20260914010000_m5_evidence_graph.sql` aplicada localmente. Relações
entre oportunidade, negócio, empresa e contato são derivadas exclusivamente do
Journal. Cada aresta tem evento de origem e intervalo de validade; referências
ausentes não apagam fatos, e valores inválidos não criam relações. Eventos tardios
reconstroem os mesmos intervalos de um replay completo. A projeção serializa por
tenant porque oportunidades podem compartilhar relações do mesmo negócio.

`GET /api/v1/opportunities/{id}/graph?depth=2` verifica acesso e licença, limita
profundidade a dois níveis e retorno a oito arestas, com timeout e proveniência.
FKs compostas impedem evidência de outro tenant. RLS permite somente leitura ao
usuário autenticado. O modelo não participa da escrita de relações.

O detalhe da oportunidade apresenta ECharts sob demanda, lista equivalente,
expansão de evidências por teclado, profundidade, atualização e estados de erro.
O bloco “Por que agora” permanece primeiro. Cache é separado por usuário e tenant;
negação de acesso oculta dados anteriores. Títulos repetidos de oportunidades no
Radar agora usam IDs para as chaves da tabela acessível, corrigindo avisos React.

Reconstrução local de 148 oportunidades existentes, sem reset ou alteração no CRM:
`.venv/Scripts/python.exe scripts/rebuild-evidence-graph.py`.

Validação: 95 testes backend aprovados, 12 integrações omitidas na suíte sem banco;
os três testes PostgreSQL de agentes/grafo passaram separadamente. O teste de grafo
inclui replay com evento tardio, igualdade do histórico, travessia, FK e RLS.
Chrome com API/Postgres reais: oito combinações claro/escuro em 1440, 820, 700 e
390 px, sem overflow, erros JS ou violações axe no painel. Evidência por teclado,
desenho/lista, profundidade, vazio e acesso negado com recuperação verificados por
`node apps/web/scripts/verify-m5-graph.cjs`. Estados vazio/negado são simulados
somente na resposta do navegador. O registro real consultado tem uma relação;
empresa/contato e segundo nível são cobertos pelo teste PostgreSQL sintético.

## Quarta entrega: consumo observado — 14/09/2026

`model_usage` registra uma observação por run, com FK composta por tenant e RLS.
Tokens vêm dos counters do Agno/OpenAI, incluindo entrada em cache. Custo calculado
tem versão de tarifa; modelo sem tarifa conhecida mantém custo ausente. Não há
retropreenchimento dos zeros históricos. A observação é persistida antes das
escritas posteriores de recomendação/política, e preserva uso recebido mesmo se
a validação da resposta falhar. Sem chave/cota, registra `not_called`; falha sem
counters é `unavailable`. A escrita idempotente alimenta `ai_usage_ledger` uma vez.

Tarifa standard de texto do [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini),
consultada em 14/09/2026: USD 0,25 entrada, 0,025 entrada em cache e 2,00 saída
por milhão de tokens. Não representa fatura, taxa especial, Batch ou Flex.
Tokens de reasoning já pertencem à saída; não são somados novamente.

A tela de Agentes distingue custo calculado, subtotal parcial e ausência de
medição; informa amostras, tokens e runs sem chamada. Latência continua sendo
duração do run. Testes verificam cálculo, cache, counters inválidos, fallback com
consumo, idempotência do ledger, totais parciais, FKs e RLS.

## Quinta entrega: chat por oportunidade — 14/09/2026

`/chat` consulta `GET /api/v1/chat/messages?scope_ref=...` e envia
`POST /api/v1/chat/messages` por SSE. Restrito a administrador/gestor, com
membership e licença rechecadas, escopo de oportunidade e histórico privado do
usuário. Conversas e mensagens têm RLS; o chat registra run sem abrir intervenção
comercial. Duplo envio é bloqueado; uma execução abandonada por mais de cinco
minutos pode ser recuperada no próximo envio.

Agno recebe apenas a ferramenta `get_context`, sem argumentos de alvo ou SQL,
sem ferramentas de escrita. Ela retorna a projeção determinística do snapshot
autorizado. A interface mostra ferramenta, texto parcial, evidências, hash e
orçamento. Só há resposta concluída após uso da ferramenta e finalização do run.
Erro/desconexão não é apresentado como resposta completa. Não se exibe raciocínio
interno. O histórico é preservado para consulta, mas **não é incluído em prompts
posteriores**: cada pergunta opera sobre a oportunidade selecionada.

O recorte de evidências tem limite de 2.500 bytes UTF-8, usado como limite superior
conservador de tokens, inclusive para texto multibyte. O painel mostra instruções
e pergunta separadamente. Este teto cobre o recorte de evidência, não o envelope
interno do SDK nem o total faturado; estes são medidos após a resposta. Citações
do painel incluem somente eventos que efetivamente couberam no recorte. O painel
mostra fontes disponíveis, não uma garantia de que toda frase gerada esteja correta.

Testes: 107 backend aprovados, 15 integrações omitidas na execução sem banco;
seis testes PostgreSQL M5 passaram separadamente. Frontend cobre fragmentação
UTF-8/SSE, desconexão sem `done` e apresentação de subtotal parcial. Chrome:
oito combinações de chat e dez de Agentes, temas claro/escuro e desktop/tablet/mobile,
sem overflow, erros JS ou violações axe detectadas. Teclado validado. No chat,
contexto/GET reais; stream de apresentação controlado, sem chamada paga.

## Evolução do chat — solicitação de 26/09/2026

A solicitação explícita do responsável pelo produto amplia o chat por oportunidade:
o usuário conversa sem selecionar um registro previamente. A busca deve localizar
oportunidades salvas no ARES e negócios acessíveis pelo adapter do CRM, preservando
a distinção entre essas entidades. Os requisitos de identidade, fontes, acesso e
movimento continuam os de [05 — UX/UI e Telas Detalhadas](https://app.notion.com/p/3c3e18aa7b0d81acb2dbf39cbbc334b9).

Critérios deste recorte:

- `scope_ref` opcional nos endpoints de histórico e envio; links contextuais
  existentes continuam compatíveis, sem exigir seletor na tela.
- Saudação simples recebe resposta curta, sem despejo de contexto comercial.
- Perguntas comerciais consultam fontes autorizadas, com busca limitada no retorno,
  origem explícita e indicação de fonte indisponível ou recorte parcial.
- Se a busca não encontra evidências, o chat responde de forma determinística e
  informa as limitações da consulta; não pede ao modelo que complete dados ausentes.
- Respostas usam Markdown, listas e tabelas quando ajudam a leitura. `react-markdown`
  e `remark-gfm` fazem a apresentação; pandas não é necessário para renderizar o chat.
- Mensagem enviada aparece imediatamente. Um indicador de processamento acompanha
  a requisição até conclusão ou falha e respeita `prefers-reduced-motion`.
- Fontes e metadados ficam disponíveis por expansão. Texto parcial nunca é rotulado
  como resposta concluída quando o stream termina com falha.
- Autorização por tenant, membership/licença ativa, histórico privado, rastreabilidade
  e proibição de escrita pelo chat permanecem obrigatórios.

O único adapter HTTP implementado neste checkout é o FakeCRM de desenvolvimento.
A busca pelo CRM real do cliente depende de adapter e credenciais homologados;
o chat deve informar essa ausência, sem apresentar o sandbox como integração real.

## Aceite ainda aberto (registro histórico de 14/09/2026)

**Não há chave OpenAI configurada no ambiente local.** O chat informa a ausência e
desabilita envio. O backend, persistência e consumo foram exercitados com provedor
sintético controlado e PostgreSQL real; streaming com OpenAI real e reconciliação
dos counters ainda precisam de validação. Configurar `ARES_OPENAI_API_KEY` somente
no `.env` do backend e reiniciar a API. Nunca inserir chave na interface ou em Git.

A M5 não está encerrada. Permanecem validação real do provedor, revisão do fluxo
com dados homologados e aceite final. A cota atual é pré-voo; reserva concorrente
de orçamento faz parte da evolução M6. Interrupções sem counters completos não
permitem afirmar custo total, e continuam identificadas como uso indisponível.

Esse registro descreve o ambiente de 14/09. Em 26/09, a configuração local foi
reverificada: modelo `gpt-5.4`, chave presente somente no backend e API saudável.
Isso não substitui os resultados de validação da evolução acima nem constitui
homologação do CRM do cliente.

## Evolução conversacional — 06/10/2026

Por solicitação explícita do usuário, o chat passa a interpretar continuações da
conversa e perguntas livres. A restrição histórica de não incluir pedidos anteriores
no prompt é substituída por até três pedidos privados nas últimas 24 horas, com
reconsulta dos registros citados. Respostas antigas não fundamentam fatos atuais.
Ferramentas de leitura com filtros estruturados permitem reformular consultas;
autorizações, isolamento, orçamento e ausência de escrita continuam obrigatórios.
Comportamento e limites estão em [Chat ARES — interpretação e continuidade](chat-conversation-2026-10-06.md).
