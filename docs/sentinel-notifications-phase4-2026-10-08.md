# Fase 4 — sentinelas configuráveis e notificações

Entrega local em 08/10/2026. Contrato oficial registrado na seção 13.6 de
[Agentes e ferramentas](https://app.notion.com/p/3c7e18aa7b0d81cba5c3d6e7cce87585).

## Configuração e execução

Os cards e o CRUD existentes foram preservados. Cada regra aceita etapas do funil,
carteira, faixa de valor com moeda explícita, sinais de risco e limiar temporal.
As condições continuam nos templates SLA vencido, ausência de responsável e falta
de atualização; não existe SQL livre nem criação arbitrária de condições pelo modelo.

A agenda aceita dias da semana, fuso IANA, janela diária e frequência ou horários
específicos. Horários inválidos, janelas invertidas, moeda ausente em filtros de
valor e combinações ambíguas são rejeitados. Janelas que atravessam a meia-noite não
são aceitas nesta entrega. Horário inexistente na transição de verão é ignorado;
horário repetido é executado uma vez. O worker atrasado fora da janela reagenda
para o próximo horário válido. Regras antigas mantêm sua compatibilidade.

Cards apresentam agenda, próxima e última execução, achados e falhas. Administradores
podem testar critérios com uma contagem completa e amostra limitada, sem salvar
achados, chamar IA ou escrever no CRM. O teste registra auditoria, exige capacidade
do plano e está sujeito aos limites de requisição existentes; não ocupa uma nova
sentinela nem consome orçamento de IA.

## Achados e caixa do sino

O detector usa consultas parametrizadas e persiste a evidência objetiva antes de
qualquer interpretação. Cada achado conserva regra/versão, snapshot, correlação,
severidade derivada do Core e histórico de revisões. O ciclo é aberto, atualizado,
resolvido ou superado. Repetir uma condição idêntica não cria outra notificação;
mudanças relevantes geram revisão e voltam a aparecer como não lidas. Resolução é
identificada pela próxima varredura, não pelo clique do usuário.

Leitura e arquivamento são pessoais e nunca resolvem o risco compartilhado. O sino
oferece caixa de entrada, não lidas, arquivadas e paginação. O contador completo e
a página usam o mesmo escopo autorizado. Membership, contrato e carteira são
revalidados no servidor; trocar responsável ou revogar acesso impede a leitura
anterior. Marcação exige a revisão esperada para evitar ações sobre versões antigas.

## Agente Sentinela separado

A interpretação é opcional e começa desligada. Sua ativação exige capacidade de
agentes no plano. O agente `sentinel-interpreter` tem definição, schema, run,
snapshot e orçamento próprios; não altera score, prioridade, políticas ou CRM.
Seu contexto é projetado pelo Context Builder a partir da revisão persistida,
com hash, referências verificadas e orçamento limitado. Cortes são informados
como limitações. O run referencia o evento específico do achado por FK com tenant.

A identidade da execução automática é a regra autorizada da empresa, com finalidade
limitada, e não uma sessão de usuário mantida indefinidamente. Contrato, capacidade,
agenda, versão e evidência são rechecados antes da chamada e da publicação.
Falhas, falta de chave ou orçamento preservam o achado objetivo e indicam estado
degradado. Uma chamada de resultado incerto não é repetida automaticamente nem
publica uma resposta tardia sobre revisão superada.

## Evidências e limites

- Backend: 234 testes sem integração e 145 testes PostgreSQL aprovados.
- Banco local: 26 migrations aplicadas e 56 contratos pgTAP aprovados.
- Frontend: 106 testes aprovados, typecheck e build de produção concluídos.
- Ruff e mypy aprovados; lint frontend sem erros, com avisos preexistentes.
- Navegador com API real: regra sintética pausada criada, critérios testados e regra
  arquivada; cards verificados em 1440, 820 e 390 px, sino em celular e Escape
  devolvendo foco. Sem erros de página ou console; apenas aviso informativo do React.
- Testes de interpretação usam executor sintético e fallback sem chave. Não houve
  chamada real à OpenAI: qualidade semântica, latência e custo reais ainda exigem piloto.

As validações são locais, com dados sintéticos, e não homologam CRM real nem ambiente
de produção. O rascunho de regras em linguagem natural era opcional e não foi incluído.
O sino ainda abre o detalhe da oportunidade; abertura de conversa contextual e
continuidade com especialistas pertencem à fase 5. O pacote Docker precisa ser
reconstruído e as migrations aplicadas no ambiente de destino antes de publicar.

Atualização posterior na mesma data: o fluxo sino → chat foi entregue na [fase 5](finding-chat-phase5-2026-10-08.md). As limitações acima registram o checkpoint original da fase 4.
