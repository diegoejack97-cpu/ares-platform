# ARES — identidade Observatório

Revisão visual de 08/09/2026, autorizada pelo responsável pelo produto. Complementa a
[especificação de UX/UI no Notion](https://app.notion.com/p/3c3e18aa7b0d81acb2dbf39cbbc334b9).
Não altera contratos de negócio, atribuição, permissões ou a stack do MVP.

## Diagnóstico e direção

O corte anterior repetia cartões de peso visual semelhante e explicações estáticas.
A composição passa a privilegiar duas perguntas: qual é a exposição observada e
qual oportunidade deve ser analisada primeiro?

- **Assinatura:** monograma ARES de dois planos cortados; canto superior direito
  chanfrado/arredondado assimétrico, pequena marca inclinada nos títulos analíticos.
  A marca não substitui os ícones funcionais Phosphor.
- **Material:** grafite mineral, marfim, cobre e aço. O console de exposição tem
  contraste próprio; superfícies usam borda iluminada, base deslocada e sombra curta.
  Gráficos e campos ficam em áreas rebaixadas, sem neon ou transparência de vidro.
- **Tipografia:** Archivo variável; hierarquia editorial e números tabulares. Textos
  de proveniência permanecem separados da leitura principal.
- **Composição:** exposição e ficha de decisão em grade assimétrica; distribuições
  por etapa, sinal e SLA; fila de cinco linhas com prioridade ao lado. A ficha é o
  primeiro item da ordenação canônica, não uma recomendação inventada no frontend.
- **Navegação:** Radar primeiro, depois Aprovações, Journal e Laboratório. Hover
  revela o rail sem deslocar conteúdo; clique fixa; clique fora/Escape recolhe;
  foco e botão mobile preservam acesso por teclado/toque.

## Movimento e integridade dos dados

ECharts mantém a instância e interpola alterações; não remonta a cada segundo.
O relógio compartilhado atualiza SLAs. Apenas a travessia de um limite de SLA
altera a série correspondente. A consulta ao CRM ativa o indicador do cabeçalho;
ele para ao terminar a consulta e não representa execução de um modelo de IA.

Números têm entrada curta e realce de delta. Toda animação não essencial respeita
`prefers-reduced-motion`. O Journal usa timestamps reais no eixo temporal.

Valores ausentes são explicitados, nunca convertidos em zero. Moedas não são
somadas entre si. Valores sem moeda ficam fora dos totais. O recorte retornado
pela API não é apresentado como todo o CRM; observação/influência não é causalidade.
Não há séries, previsões, agentes ativos ou receita incremental fabricados.

## Código e verificação

- Tokens e superfícies: `apps/web/src/styles/observatory.css`.
- Composição: `apps/web/src/features/opportunities/observatory-radar.css`.
- Marca: `apps/web/src/components/ares-mark.tsx`.
- Renderer e metadados compartilhados: `apps/web/src/charts/`.
- Verificação somente leitura: `node apps/web/scripts/verify-observatory.cjs`.

O verificador usa a stack local já iniciada, não altera a massa do CRM, e cobre
login, menu, fila progressiva, quatro alternativas tabulares, tema persistente,
cinco rotas em 1440/1024/390 px e auditoria axe. Evidências e relatório são gerados
em `output/playwright/observatory/` (ignorados pelo Git). `ARES_WEB_URL` permite
apontar o teste para outra porta local. Testes não substituem revisão humana de UX.

Comandos complementares:

```powershell
npm run test --workspace @ares/web
npm run lint --workspace @ares/web
npm run build --workspace @ares/web
graphify update .
```

O redesign não conclui Command Center/Impacto ARES nem a integração com um CRM real.
Essas entregas continuam seguindo seus próprios critérios de aceite.

## Evidência da revisão de 08/09/2026

Verificação executada com 25 oportunidades sintéticas já existentes, sem semear ou
resetar o banco: 30 combinações de rota/tema/largura sem transbordamento, 10 auditorias
axe (WCAG A/AA no desktop) sem violações detectadas e nenhum erro de console. Passaram
hover/fixação/fechamento/teclado/Escape, menu mobile, persistência do tema, rolagem
progressiva e as quatro alternativas em tabela. As capturas foram inspecionadas.

Testes de componentes: 13 aprovados. Lint sem erros, com dois avisos preexistentes
de fast refresh nas primitivas Button/Badge. Build e TypeScript aprovados; o build
ainda sinaliza o tamanho do chunk principal, uma oportunidade de otimização separada.
