# ARES — correções e situação do MVP, 03/10/2026

As correções abaixo foram implementadas no checkout local e verificadas com dados sintéticos. O banco do ambiente atual não foi resetado. Não houve implantação pública nem escrita em CRM real.

## O que foi corrigido

| Item da auditoria | Resultado |
| --- | --- |
| MVP-01: estado de uma empresa aparecia após troca de conta | O usuário e a empresa ativa possuem um cliente de consultas exclusivo. Logout desmonta a interface e descarta consultas, cache e rascunhos; respostas antigas não entram na nova sessão. |
| MVP-02: aprovação sem aplicação do papel exigido | API e serviço verificam a associação ativa registrada no banco, o papel exigido, o escopo da oportunidade e o prazo da aprovação. Negação não cria decisão, intenção nem job. A interface depende de permissão explícita do servidor e retira controles quando o prazo expira. |
| MVP-06: contrato podia mudar entre aprovação e execução | Antes da escrita, o executor verifica empresa, plano Connect, vencimento, cobrança, papel atual do aprovador, escopo e política/capacidade vigente. Bloqueio cancela a intenção, encerra a oportunidade com motivo auditável e torna o job terminal. Reativar o contrato não ressuscita a intenção cancelada. |
| MVP-07: formatação e verificações locais | Corrigida a formatação divergente. Ruff, mypy, lint, typecheck, format:check e build passaram. Resultado da suíte frontend consolidado no relatório de evidências abaixo. |
| MVP-08: integração de banco podia ser pulada | Criado job de CI com Supabase local, migrations, pgTAP e integração Python. O runner falha sem URL explícita, sem testes ou com testes pulados. O job remoto ainda precisa executar na revisão publicada; o ensaio local de criação do schema foi concluído. |

Vendedores podem solicitar recomendações somente de oportunidades atribuídas ao seu usuário. Administradores e gestores têm acesso ao escopo da empresa; auditores permanecem somente leitura. A aprovação respeita o papel configurado na política, não o texto de um papel enviado pelo cliente.

O bloqueio comercial usa locks durante o envio ao provedor. Uma suspensão anterior ao envio impede a escrita; uma suspensão que chega depois de uma chamada já iniciada aguarda sua conclusão. Isso não desfaz ações externas já enviadas.

## Evidências

| Verificação | Resultado confirmado |
| --- | --- |
| Backend sem dependência de PostgreSQL | 172 testes passaram. |
| Backend com PostgreSQL descartável | 67 testes passaram, zero pulados, incluindo vencimento durante espera por lock. |
| Contratos SQL e isolamento por RLS | 56 verificações pgTAP passaram; fixtures revertidas por rollback. |
| Migrations da aplicação em schema novo | 20 aplicadas; nenhum dado da aplicação atual foi copiado. |
| Frontend completo | 96 testes passaram, zero falhas e zero pulados; execução com um worker e timeout de 15 segundos na CLI. |
| Navegador | 12 cenários de autorização, responsividade e teclado passaram; nenhum erro de console, overflow nas larguras verificadas ou violação axe encontrada. |
| Troca de empresas no navegador | Empresa A → logout → Empresa B, com leitura B atrasada 5 segundos: registro privado sintético de A não apareceu. |

Evidências locais: [PostgreSQL](../output/mvp-fixes-2026-10-02/postgres-tests.txt), [pgTAP](../output/mvp-fixes-2026-10-02/pgtap.json), [migrations](../output/mvp-fixes-2026-10-02/migrations.json), [frontend](../output/mvp-fixes-2026-10-02/frontend-verification.md), [navegador](../output/mvp-fixes-2026-10-02/frontend-browser-checks.json) e [troca de empresas](../output/mvp-fixes-2026-10-02/cross-tenant-cache-proof.json). A pasta output é ignorada pelo Git.

Persistem nove avisos anteriores no lint frontend e o aviso de bundle principal grande: aproximadamente 933 kB minificado / 288 kB gzip. O pytest também relatou impossibilidade de gravar seu cache local no Windows; os testes terminaram com sucesso.

## O que ainda falta para um piloto com dados reais

1. **Homologar um CRM real:** escolher o primeiro provedor, implementar seu adapter e testar autenticação, mapping, paginação, sincronização, reconciliação, escrita aprovada, conflitos e idempotência no sandbox oficial.
2. **Resolver provedor e credenciais por conexão/empresa:** o isolamento no banco e na sessão não substitui o roteamento correto do CRM. Validar duas empresas com IDs externos iguais e segredos independentes.
3. **Concluir o recebimento durável de webhooks por conexão:** autenticação e repetição após falha devem produzir um único processamento.
4. **Preparar staging/produção:** HTTPS, Supabase próprio, secrets de backend, redirects e CORS, perfil sem FakeCRM/memory, tick supervisionado e smoke pela URL hospedada.
5. **Ensaiar operação e recuperação:** backup/restore, retomada de jobs sem escrita duplicada, alertas de atraso e tratamento de reservas de IA interrompidas.
6. **Concluir onboarding conforme o escopo comercial:** convite, verificação de e-mail e recuperação de senha. Um piloto assistido pode usar procedimento manual documentado; liberação pública exige a jornada completa.

Também permanecem os itens de frescor dos dados, drenagem de backlog dos sentinelas, consultas e memória do chat, configuração comercial e otimização de UX listados na [auditoria completa](../output/mvp-readiness-2026-10-01/melhorias-priorizadas.md). Esta entrega não marca esses itens como resolvidos.

**Veredito:** estas correções melhoram a segurança e a base de entrega e permitem continuar a demonstração sintética. Ainda não há evidência suficiente para declarar o SaaS pronto para produção com dados reais de clientes. O CRM é o principal gate funcional; hospedagem, segregação de credenciais e recuperação também precisam de aceite.

## Reproduzir a integração obrigatória

Use um Supabase de CI ou outro banco explicitamente descartável com todas as migrations e o seed sintético. Nunca execute db:reset no ambiente do cliente para obter uma validação.

```powershell
# Configure ARES_TEST_DATABASE_URL e ARES_DATABASE_URL para o banco descartável.
$env:ARES_TEST_DATABASE_DISPOSABLE = "1"
$env:ARES_EVENT_JOURNAL_BACKEND = "postgres"
$env:ARES_OPENAI_API_KEY = ""
.\.venv\Scripts\python.exe scripts/seed-integration-tests.py
npm run supabase -- test db --db-url $env:ARES_TEST_DATABASE_URL
.\.venv\Scripts\python.exe scripts/run-postgres-tests.py
```

Os testes de aprovação/executor adicionais estão em test_postgres_decision_authorization.py; as regressões de sessão estão em auth-gate.test.tsx. As instruções oficiais de produto continuam na [documentação técnica e de produto do Notion](https://app.notion.com/p/3c0e18aa7b0d801d8898d2402fc737b3).
