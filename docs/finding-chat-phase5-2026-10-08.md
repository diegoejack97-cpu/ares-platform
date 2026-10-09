# Fase 5 — sino → chat e conversa contextual

Implementada e validada localmente em 08/10/2026. Contrato registrado na seção 13.7
de [Agentes e ferramentas](https://app.notion.com/p/3c7e18aa7b0d81cba5c3d6e7cce87585).

## Fluxo entregue

1. O sino abre `/chat?finding=<id>` e envia ao backend somente o ID do achado.
2. O servidor revalida membership, tenant, contrato e carteira; lê a evidência
   persistida e consulta o estado atual. O seller acessa somente o achado autorizado
   de sua carteira; o acesso ao chat geral continua reservado a admin/manager.
3. Uma conversa pessoal é criada ou retomada. Abertura idempotente combina usuário,
   achado, revisão e assinatura do estado atual/regra. Clique duplicado e reconexão
   não duplicam a explicação nem geram cobrança de IA. Se o estado mudou antes da
   próxima varredura, reabrir registra uma nova explicação objetiva, no mesmo thread.
4. A notificação é marcada lida após a abertura persistida. A interface mostra
   negócio, regra, detecção, condição atual e navegação de volta. Evidências antigas
   permanecem históricas; não são usadas como prova do estado atual.
5. Perguntas de continuidade reconsultam os fatos e mantêm referências do histórico.
   O usuário pode perguntar sobre risco, mudanças, próximos passos, comparações,
   contagem, valor e funções do produto. Dados ausentes continuam explícitos.

A explicação de abertura é determinística e não chama o modelo. Perguntas livres
podem usar o agente do chat quando o provedor está disponível; sem chave, existe
fallback objetivo para o contexto do achado e consultas tipadas. Isso não equivale
a raciocínio aberto de um modelo real nem a treinamento/fine-tuning.

## Comunicação entre especialistas

O roteador do servidor escolhe finalidades limitadas: diagnóstico, consulta comercial,
comparação/priorização, orientação de próximos passos e ajuda. Não escolhe permissões
nem escreve SQL a partir do modelo. Diagnósticos especializados existentes só entram
no contexto quando o runtime da fase 3 os valida como atuais; a validade é rechecada
durante a resposta. Runs e contexto permanecem associados à mensagem.

O usuário pode solicitar triagem/diagnóstico por um botão compacto, somente quando
a rotina e a capacidade do plano permitem. O botão utiliza o runtime durável existente,
com chave idempotente, contrato, orçamento e auditoria; não abre um executor paralelo.
Perguntas não aprovam intervenções. O detalhe da oportunidade mantém acesso às análises
e ao fluxo de decisão já implementado.

Agentes proativos de priorização, análise comercial e recomendação das fases 6–7
não são simulados como entregues aqui: nesta fase, comparação e métricas ainda usam
consultas autorizadas e orientação do chat. Qualidade semântica e custo com modelos
reais continuam dependentes do piloto da fase 0.

## Histórico, interface e feedback

- Histórico paginado com cursor validado dentro da conversa pessoal; carregar
  mensagens anteriores preserva a posição e elimina duplicações na interface.
- Mensagem sai do composer ao enviar, Enter envia e Shift+Enter quebra linha;
  permanecem os três pontos discretos e lentos, interrupção e recuperação da leitura.
- Perguntas sugeridas derivam das capacidades reais. O bloco de origem não despeja JSON.
- Feedback útil/não útil aceita motivo opcional e fica associado à mensagem, contexto
  e run no servidor. O navegador não fornece esses vínculos como autoridade.
- Ler/avaliar uma resposta não modifica risco, score, policy, aprovação ou CRM.

## Verificação

| Verificação            | Resultado                                                                                |
| ---------------------- | ---------------------------------------------------------------------------------------- |
| Backend sem integração | 241 testes aprovados                                                                     |
| PostgreSQL             | 149 testes aprovados; gate sem testes ignorados                                          |
| Frontend               | 109 testes aprovados                                                                     |
| Contratos do banco     | 56 testes pgTAP aprovados                                                                |
| Qualidade              | Ruff, mypy, typecheck e build aprovados; lint sem erros, avisos preexistentes            |
| Banco local            | 27 migrations aplicadas                                                                  |
| Navegador real         | Chrome e Firefox: sino, origem, duas perguntas, feedback, Enter/Shift+Enter              |
| Responsividade         | Desktop 1440 px, tablet 820 px e celular 390 px; captura final após estabilizar o drawer |

Os testes cobrem abertura simultânea, reabertura após mudança, condição encerrada,
referências atuais, revogação por troca de responsável, tenant incorreto, emissão
bloqueada após perda de acesso, cursor pertencente à conversa e feedback pessoal.
A caixa e o chat foram exercitados com API real e dados locais sintéticos.

As validações finais de continuidade usam chave vazia e fallback, não uma avaliação
de qualidade do provedor. Uma execução inicial do novo teste herdou a configuração
local de IA; o teste foi corrigido para usar explicitamente `SecretStr("")`. O gate
PostgreSQL usa API e fixtures no mesmo banco isolado. O diretório temporário de pytest
foi definido dentro de `output/` devido à permissão do temporário padrão do Windows.

Não há certificação de produção ou homologação de CRM real. Antes de publicar,
reconstruir o pacote Docker e aplicar as 27 migrations no destino. RAG permanece na
fase 8; a evolução não depende de fine-tuning nesta entrega.

## Revalidação após reinício em segundo plano

Em 08/10/2026, API e worker foram reiniciados com `Start-Process -WindowStyle Hidden`,
logs redirecionados para `output/` e configuração normal de IA preservada. O comando
retornou ao terminal; nenhum servidor ficou anexado à sessão de validação.

- API: `/health/ready` retornou `ready`.
- Worker: healthcheck aprovado e tick concluído no último minuto.
- Banco local: 27 migrations aplicadas.
- Regressão dirigida: 19 testes de regras/roteamento, 11 testes PostgreSQL de
  notificações/continuidade e 11 testes frontend do sino, sentinelas e chat aprovados.

A primeira tentativa de regressão PostgreSQL apontou para o banco padrão vazio do
container de testes e falhou na preparação. A execução foi corrigida para o banco
isolado `ares_test_mvp_20261005`, sem alteração no código ou nos dados do ambiente
local de apresentação. As limitações de CRM real e qualidade semântica permanecem.
