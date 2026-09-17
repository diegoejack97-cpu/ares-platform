# Provedor — provisionamento e recuperação

Este procedimento é administrativo, fora das APIs do produto. Precisa de acesso
ao Supabase Auth e banco por um operador autorizado. Não usar o usuário
`admin@ares.local` do produto: o provedor deve ter conta e sessão separadas.

1. Criar ou recuperar a conta dedicada no Supabase Auth. Confirmar identidade
   antes de redefinir credenciais. Não copiar senha, token ou chave para logs/Git.
2. Obter o UUID dessa conta. Confirmar que não há linhas em `memberships` para
   ela e conferir se existe outro operador ativo. A checagem da API recusa uma
   identidade que também pertença ao produto, mesmo com membership inativa.
3. Com credencial administrativa do banco, cadastrar explicitamente esse UUID
   em `private.provider_operators`, com motivo. A migration não cadastra ninguém.
   Exemplo parametrizado para psycopg, executado dentro de uma transação:

   ```sql
   insert into private.provider_operators(user_id,reason)
   values (%s, %s);
   ```

   O índice permite somente um operador ativo. Para substituir uma conta perdida,
   confirmar a nova identidade primeiro; desativar a antiga e cadastrar a nova na
   mesma transação. Preservar os usuários antigos e a autoria dos audits.
4. Encerrar sessões antigas comprometidas no Auth, depois iniciar uma nova sessão
   dedicada. A API consulta `auth.sessions` a cada operação; um token ainda não
   expirado de uma sessão removida é recusado. Operador inativo também é recusado.
5. Validar `GET /api/v1/admin/tenants` com a nova sessão. Consultar `provider_audit`
   administrativamente para confirmar o registro da leitura. Verificar que o
   token de admin do produto continua sem acesso às rotas de provedor.

Cobrança, licença, cota e entitlement de cliente não participam da autorização
do provedor. Não criar membership em um tenant para tentar recuperar o acesso.
O painel `/admin` usa armazenamento de sessão separado (`sessionStorage`, chave
`ares-provider-session`) e a API exige a identidade dedicada.

Os testes PostgreSQL desta entrega exercitam criação da identidade sintética,
revogação de sessão e rejeição de membership, com rollback. A recuperação real
de uma conta dedicada deve ser ensaiada antes do go-live; não foi executada
automaticamente nesta etapa.
