# FakeCRM HTTP Sandbox

O sandbox é um CRM mínimo de contrato para desenvolver e homologar o ARES Connect sem
depender de credenciais ou dados de um cliente. Ele não é um produto CRM nem substitui a
homologação do adapter real.

## O que ele oferece

- processo FastAPI independente em `http://127.0.0.1:8010`;
- OpenAPI interativo em `http://127.0.0.1:8010/docs`;
- 20 empresas, 40 contatos, 60 oportunidades e 60 atividades sintéticas;
- datas, IDs e cenários reproduzíveis após cada reset;
- paginação por cursor e watermark para ensaiar leitura incremental;
- escrita de tarefa, nota e etapa com `Idempotency-Key`;
- conflito de versão em atualização de etapa;
- fixture de webhook assinada por HMAC;
- falhas controladas: 401, 404, 409, 429, 500 e timeout.

Todos os registros usam IDs fictícios, emails no domínio reservado `example.test` e
`synthetic: true`. Dados pessoais ou payloads reais não devem ser colocados no sandbox.

## Executar

```powershell
npm run dev:sandbox
```

Em outro terminal:

```powershell
npm run m4:sandbox:verify
```

O token local padrão é `local-sandbox-key`. Ele é apenas uma conveniência de desenvolvimento e
deve ser substituído fora da máquina local.

## Conectar o ARES ao processo HTTP

Configure o backend antes de iniciá-lo:

```powershell
$env:ARES_CRM_PROVIDER = "http_fake"
$env:ARES_FAKE_CRM_BASE_URL = "http://127.0.0.1:8010"
$env:ARES_FAKE_CRM_API_KEY = "local-sandbox-key"
npm run dev:api
```

O valor padrão continua sendo `embedded_fake`, preservando os testes e a jornada das M1–M3.
Quando o CRM do cliente estiver disponível, um adapter do mesmo contrato substituirá essa
configuração; Core, Policy, workers e auditoria não devem conhecer detalhes do fornecedor.

## Cenários de falha

Envie `X-FakeCRM-Scenario` nas rotas `/v1/*` com um destes valores:

- `unauthorized`;
- `not_found`;
- `conflict`;
- `rate_limit` (inclui `Retry-After: 1`);
- `server_error`;
- `timeout`.

Esses cenários existem para testar timeout, retry, reconciliação e classificação de erros. Eles
não autorizam retry cego de mutações: toda repetição de escrita deve preservar a mesma chave de
idempotência.

## Limite desta entrega da M4

Concluído neste recorte: serviço HTTP, massa sintética, adapter, paginação, idempotência,
concorrência otimista, webhook e suíte contratual.

Continuam abertos: descoberta e mapeamento do schema do CRM escolhido, credenciais, leitura
incremental real, reconciliação, write-back homologado e Kanban espelhado. Essas etapas exigem a
API e as regras do CRM do primeiro cliente; portanto a M4 inteira não está concluída.
