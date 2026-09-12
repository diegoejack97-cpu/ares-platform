# M4 — aceite local (12/09/2026)

Implementação local concluída com FakeCRM HTTP. A integração e homologação com o CRM
do cliente continuam pendentes; nenhuma capacidade real do cliente foi presumida.

## Entregue

- Mapeamento de campos/etapas versionado, validação e exclusividade de módulo por tenant.
- Sync paginado retomável, checkpoint atômico, overlap, deduplicação por versão,
  histórico de 90/180 dias e reconciliação sem exclusão dos registros ausentes.
- Kanban com confirmação humana, alternativa por seletor, tratamento de conflito,
  repetição do mesmo intento quando o resultado é incerto, correlação e auditoria SQL.
- Worker local dedicado às filas de integração, incluído em `npm run dev:all`.
- Escrita humana não é intervenção de IA: `ares_intervention=false`, atribuição `none`.

## Evidência

- Duas migrations aplicadas sem reset; security advisors sem apontamentos.
- Backend: 80 testes aprovados (9 testes dependentes de banco omitidos da suíte geral).
- PostgreSQL M4: 3 testes aprovados separadamente; tenant isolado, rollback no fim.
- Frontend: 19 testes, typecheck e build aprovados.
- Fluxo real local: 60 negócios, mudança confirmada e etapa restaurada.
- Browser: 8 capturas (quatro larguras, dois temas), sem overflow, erros de execução
  ou violações axe. `output/playwright/m4-live/report.json` (ignorado pelo Git).

Abrir: http://localhost:5173/pipeline . Integração e cargas permite gerir o contrato,
reconciliar o funil e solicitar histórico. O CRM externo continua sendo a autoridade.

## Limites explícitos

Os endpoints M4 são development-only enquanto só existir o adaptador sintético.
A janela histórica importa o estado de registros alterados no período; não inventa
eventos históricos que o provedor não disponibilize. A homologação real deve confirmar
paginação, versões, rate limits, histórico, permissões e contratos de escrita.

O sandbox já em execução é preservado. Se não oferecer GET de negócio individual,
o adaptador confirma pela leitura paginada (limitada a 20 páginas). Novas instâncias
incluem GET individual e paginação por snapshot. Não reiniciar o sandbox para apagar
divergências de teste; auditar/reconciliar a origem.

O upgrade visual global é uma frente separada: este aceite cobre o Kanban M4,
não encerra a revisão de todas as telas existentes. Alterações permanecem locais,
sem commit/push nesta entrega. Avisos não bloqueantes: Fast Refresh e bundle >500 kB.
