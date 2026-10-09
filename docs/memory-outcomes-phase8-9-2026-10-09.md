# Memória comercial e avaliação de resultados — fases 8 e 9

Entrega em 09/10/2026. Implementação e validação local com dados sintéticos. Os contratos foram registrados no capítulo oficial Agentes e ferramentas, seções 13.9 e 13.10, e conferidos após a atualização. Homologação de CRM real, avaliação semântica com modelos reais e validação hospedada continuam pendentes.

## Fase 8: memória comercial autorizada

A tela **Agentes → Memória comercial e resultados** permite configurar retenção, consentimento e envio de fontes verificadas. Memória, processamento externo, avaliação automática e publicação de episódios começam desligados. O administrador da empresa controla esses recursos dentro dos limites contratados; a Central Admin configura armazenamento e orçamento de indexação.

O formato inicial é TXT ou Markdown UTF-8, até 256 KiB por arquivo. O original fica no PostgreSQL privado, separado dos trechos e vetores. Cada documento registra fonte, versão, hash, validade, classificação, papéis, finalidade e proprietário quando necessário. Atualizações exigem versão esperada e justificativa; a configuração também exige justificativa auditável. O formulário envia apenas campos editáveis, sem reenviar metadados de auditoria.

O Context Builder expõe a consulta de memória. A busca combina FTS em português e pgvector com 1.536 dimensões, filtrando empresa, papel, proprietário, finalidade, versão e validade antes do ranqueamento. Sem consentimento ou chave há busca textual local. Com consentimento explícito, textos dos documentos e perguntas podem ser enviados à OpenAI para embeddings. A empresa deve avaliar as condições de tratamento e retenção do provedor antes de usar dados de clientes.

A indexação usa jobs duráveis, limites de armazenamento, orçamento diário específico e quota global de IA. Conteúdo inalterado reutiliza vetores; consumo confirmado é registrado e execução incerta preserva reserva conservadora. A autorização e o consentimento são revalidados antes da publicação. Consultas sem fontes autorizadas não chamam o provedor.

O chat consulta playbooks e procedimentos com trechos literais e referências a documento, versão e trecho. Histórico e citações são revalidados: substituição, expiração, retirada de acesso ou remoção tornam a fonte indisponível. Remoção explícita e expiração retiram conteúdo e vetores; auditoria mantém metadados. Não há indexação do código-fonte nem treinamento automático.

## Fase 9: explicar resultados sem alterar fatos

O agente independente `outcome-evaluator` lê a cadeia de intervenção, recomendações, decisões, execuções, estado anterior/posterior e outcome observado. Não executa ações no CRM e não altera valores financeiros. Ausência de resultado permanece **pendente**, sem chamada ao modelo e sem virar zero.

A avaliação registra janela de observação, resultado tardio e intervenções concorrentes. A saída possui esquema fechado, referências e alegações verificadas contra campos literais do contexto; explicações não estabelecem causalidade. Permissões, configuração e hash dos fatos são checados novamente antes de salvar. Sem modelo há explicação determinística sinalizada como degradada.

O painel **Avaliação de resultados** aparece no detalhe da oportunidade. **Impacto ARES** mostra adoção, rejeição, falhas, mudança de estado e resolução de risco com denominadores e período sobre a carteira autorizada completa. Tempo de resposta do cliente permanece indisponível: ainda não existe evento tipado suficiente para calculá-lo.

Feedback é opinião separada dos fatos. Publicação de episódio verificado é manual, requer administrador e habilitação explícita, e usa fatos observados. Corrigir o outcome marca o episódio derivado como superado e o exclui da recuperação, preservando o histórico original; não apaga a trilha de auditoria.

## Avaliação e liberação

O conjunto sintético rotulado obteve recall@5 = 1,0, precisão@5 = 1,0 e fidelidade de citações = 1,0; os casos incluem uma fonte semelhante de outra empresa. Há testes de recuperação, fidelidade de citações e isolamento, além de testes de output inventado, consumo, revogação e contextos concorrentes. `scripts/evaluate-ai-release.py` compara baseline e candidato do mesmo conjunto/hash, exige versões de modelo/prompt, ausência de regressões de segurança e revisão humana identificada. O script não modifica prompts, modelos, Policy ou deployment. Esses testes não substituem avaliação semântica com usuários e modelos reais.

## Evidências de validação

- Backend: 262 testes unitários e 173 testes na suíte completa de integração PostgreSQL passaram. A bateria final específica passou em 17 testes, incluindo revogação de acesso e a cadeia completa de intervenção. Ruff e mypy (126 arquivos) passaram.
- Banco: 109 verificações pgTAP passaram. As quatro migrations aditivas desta entrega foram aplicadas no Supabase local e no PostgreSQL isolado de testes; total de 32 migrations.
- Frontend: 115 testes passaram na suíte serial; o único caso restante detectou o reenvio de metadados da configuração e foi corrigido. A repetição do arquivo afetado passou nos quatro testes. Typecheck e build passaram; lint sem erros, com nove avisos existentes. A suíte concorrente sofreu timeouts sob carga. Há também aviso de chave React no teste preexistente de Licenças, fora dos novos painéis.
- Navegador: salvamento real e persistência de configuração, desativação inicial, teclado, estados vazios e responsividade verificados em Agentes e Impacto nas larguras 1440, 820 e 390 pixels, sem overflow ou erros de console. O detalhe da oportunidade também foi verificado em desktop e celular. Evidências locais ficam em `output/agent-phase8-9-2026-10-09/` e não são publicadas no Git.
- Nenhum teste enviou documentos ou código a um modelo externo. Embeddings híbridos foram testados com vetores sintéticos no pgvector real.

## Limites e operação

PDF, DOCX, OCR e conectores de documentos ficam para evolução posterior. A filtragem automática de conteúdo sensível é uma proteção parcial: a empresa precisa revisar e retirar dados pessoais antes de enviar fontes. O chat usa recuperação citada para memória; isso não equivale a todos os especialistas já utilizarem todos os documentos. A lista inicial de documentos é limitada a 100 itens.

As validações literais não provam qualidade semântica de uma explicação. Antes de atender clientes, concluir piloto com modelos reais, fontes revisadas, CRM homologado e ambiente hospedado. A fase 10 continua pendente. Para desabilitar operacionalmente a entrega, desligar memória, processamento externo, avaliação e episódios em Agentes; manter as migrations e a auditoria, sem remover tabelas ou histórico.
