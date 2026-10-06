import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  ArrowRightIcon,
  ArrowUpRightIcon,
  CrosshairIcon,
  FunnelIcon,
  PulseIcon,
  ShieldCheckIcon,
} from "@phosphor-icons/react";
import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
  type InfiniteData,
} from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Freshness } from "@/components/live/freshness";
import { LiveValue } from "@/components/live/live-value";
import { SlaCountdown } from "@/components/live/sla-countdown";
import { useLiveClock } from "@/lib/live-clock";
import { safeSum } from "@/lib/numbers";
import { AresMark } from "@/components/ares-mark";
import { getOpportunities, getOpportunityAnalytics } from "./api";
import { money, priorityLabels, signalLabels } from "./format";
import { RiskDistributionChart } from "./risk-distribution-chart";
import { ScoreBar } from "./score-bar";
import type { OpportunityListItem, OpportunityPage } from "./types";
import "./radar-v2.css";
import "./observatory-radar.css";

const RadarIntelligenceCharts = lazy(() =>
  import("./radar-intelligence-charts").then((module) => ({
    default: module.RadarIntelligenceCharts,
  })),
);

const emptyItems: OpportunityListItem[] = [];
const ROW_BATCH = 5;

function IntelligenceSkeleton() {
  return (
    <section
      className="radar-intelligence-grid intelligence-loading"
      aria-label="Preparando análises do Radar"
    >
      <i />
      <i />
      <i />
    </section>
  );
}

export function RadarPage() {
  const [state, setState] = useState("");
  const [minScore, setMinScore] = useState(0);
  const [visibleCount, setVisibleCount] = useState(ROW_BATCH);
  const tableWrapRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<HTMLDivElement>(null);
  // The charts describe the whole tenant, not the page the table happens to show.
  const analytics = useQuery({
    queryKey: ["opportunity-analytics"],
    queryFn: getOpportunityAnalytics,
    refetchInterval: 30_000,
  });
  const query = useInfiniteQuery<
    OpportunityPage,
    Error,
    InfiniteData<OpportunityPage>,
    readonly unknown[],
    string | undefined
  >({
    queryKey: ["opportunities", state, minScore],
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    queryFn: ({ pageParam }) =>
      getOpportunities({
        state: state || undefined,
        minScore: minScore || undefined,
        cursor: pageParam,
      }),
    placeholderData: keepPreviousData,
    structuralSharing: true,
    refetchInterval: 15_000,
  });
  const items = useMemo(() => {
    if (!query.data) return emptyItems;
    return [
      ...new Map(
        query.data.pages
          .flatMap((page) => page.items)
          .map((item) => [item.id, item]),
      ).values(),
    ];
  }, [query.data]);
  const now = useLiveClock();
  const atRiskValue = useMemo(
    () =>
      safeSum(
        items.filter((item) => item.currency === "BRL"),
        "deal_value",
      ),
    [items],
  );
  const otherCurrencies = useMemo(
    () => [
      ...new Set(
        items
          .map((item) => item.currency)
          .filter((currency) => currency && currency !== "BRL"),
      ),
    ],
    [items],
  );
  const missingCurrencyCount = items.filter((item) => !item.currency).length;
  const focus = items[0];
  const chartState = query.isError
    ? "error"
    : query.isLoading
      ? "loading"
      : query.dataUpdatedAt && now - query.dataUpdatedAt > 90_000
        ? "stale"
        : "ready";
  const [toast, setToast] = useState(false);
  useEffect(() => {
    let timeout: ReturnType<typeof setTimeout>;
    const notify = () => {
      setToast(true);
      clearTimeout(timeout);
      timeout = setTimeout(() => setToast(false), 5_000);
    };
    window.addEventListener("ares:sla-overdue", notify);
    return () => {
      window.removeEventListener("ares:sla-overdue", notify);
      clearTimeout(timeout);
    };
  }, []);
  const overdueCount = useMemo(
    () =>
      items.filter(
        (item) => item.sla_at && new Date(item.sla_at).getTime() < now,
      ).length,
    [items, now],
  );
  const unassignedCount = useMemo(
    () => items.filter((item) => !item.owner_user_id).length,
    [items],
  );
  const visibleItems = items.slice(0, visibleCount);
  const hasMore = visibleCount < items.length || query.hasNextPage;
  const { isFetchingNextPage, hasNextPage, fetchNextPage } = query;

  const revealNextBatch = useCallback(async () => {
    if (isFetchingNextPage) return;
    if (visibleCount >= items.length && hasNextPage) {
      await fetchNextPage();
      setVisibleCount((current) => current + ROW_BATCH);
    } else {
      setVisibleCount((current) => Math.min(current + ROW_BATCH, items.length));
    }
  }, [
    items.length,
    visibleCount,
    isFetchingNextPage,
    hasNextPage,
    fetchNextPage,
  ]);

  useEffect(() => {
    if (!hasMore || !loadMoreRef.current || !tableWrapRef.current) return;
    if (typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && (tableWrapRef.current?.scrollTop ?? 0) > 0)
          revealNextBatch();
      },
      { root: tableWrapRef.current, threshold: 0.8 },
    );
    observer.observe(loadMoreRef.current);
    return () => observer.disconnect();
  }, [hasMore, revealNextBatch, visibleCount]);

  function resetProgressiveList() {
    setVisibleCount(ROW_BATCH);
    if (tableWrapRef.current) tableWrapRef.current.scrollTop = 0;
  }

  return (
    <main
      className="workspace radar-page radar-v2 observatory"
      data-fetching={query.isFetching}
    >
      <header className="page-header radar-page-header">
        <div>
          <span className="eyebrow">ARES Connect / Observatório comercial</span>
          <h1>
            Radar ARES
            <span className="heading-slash" aria-hidden>
              {" "}
              /
            </span>
          </h1>
          <p>O risco em perspectiva. A próxima decisão em foco.</p>
        </div>
        <div className="radar-header-actions">
          <Link className="radar-operations-link" to="/command-center">
            Visão operacional <ArrowUpRightIcon aria-hidden />
          </Link>
          <div className="radar-sync">
            <span className="sync-indicator" aria-hidden>
              <i />
              <i />
              <i />
              <i />
            </span>
            <span>
              <b>
                {query.isFetching
                  ? "Consultando o CRM"
                  : query.isError
                    ? "Leitura indisponível"
                    : "Leitura do CRM"}
              </b>
              <Freshness timestamp={query.dataUpdatedAt} />
            </span>
          </div>
          <Button
            variant="outline"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
          >
            <PulseIcon aria-hidden />{" "}
            {query.isFetching ? "Atualizando" : "Atualizar radar"}
          </Button>
        </div>
      </header>

      {query.isError && query.data ? (
        <div className="route-status" role="alert">
          A atualização falhou. Exibindo a última leitura bem-sucedida.
          <Button variant="outline" onClick={() => void query.refetch()}>
            Tentar novamente
          </Button>
        </div>
      ) : null}
      <section className="observatory-overview" aria-label="Resumo do Radar">
        <article className="exposure-console">
          <div className="console-caption">
            <span>
              <i aria-hidden />
              EXPOSIÇÃO NO RECORTE
            </span>
            <span>BRL / 01</span>
          </div>
          <div className="exposure-reading">
            <span>Valor observado em risco</span>
            <strong className={!atRiskValue.valid ? "no-value" : ""}>
              {atRiskValue.valid ? (
                <LiveValue value={atRiskValue.total} format={money} />
              ) : query.isLoading ? (
                "Lendo valores…"
              ) : (
                "Valor não informado"
              )}
            </strong>
            <p>
              Valor dos negócios em observação. Não representa receita
              recuperada.
            </p>
            <AresMark className="console-monogram" />
          </div>
          {atRiskValue.partial ? (
            <p className="console-notice">
              Total parcial · {atRiskValue.missing} registros em BRL sem valor
              válido, excluídos da soma.
            </p>
          ) : null}
          {missingCurrencyCount ? (
            <p className="console-notice">
              {missingCurrencyCount} registros sem moeda excluídos dos totais.
            </p>
          ) : null}
          {otherCurrencies.map((currency) => {
            const total = safeSum(
              items.filter((item) => item.currency === currency),
              "deal_value",
            );
            return (
              <p className="console-notice" key={currency}>
                {currency}:{" "}
                {total.valid
                  ? money(total.total, currency)
                  : "valor não informado"}
                {total.partial ? ` · ${total.missing} valores ausentes` : ""}.
                Sem conversão entre moedas.
              </p>
            );
          })}
          <dl className="console-metrics">
            <div>
              <dt>Em observação</dt>
              <dd>
                <LiveValue value={query.data ? items.length : null} empty="—" />
              </dd>
              <dd className="metric-description">oportunidades no recorte</dd>
            </div>
            <div>
              <dt>Prazo excedido</dt>
              <dd>
                <LiveValue
                  value={query.data ? overdueCount : null}
                  empty="—"
                  worsening
                />
              </dd>
              <dd className="metric-description">SLA vencido</dd>
            </div>
            <div>
              <dt>Sem responsável</dt>
              <dd>
                <LiveValue
                  value={query.data ? unassignedCount : null}
                  empty="—"
                  worsening
                />
              </dd>
              <dd className="metric-description">aguardam atribuição</dd>
            </div>
          </dl>
          <div className="console-source">
            <span>Fonte · {query.data?.pages[0]?.source ?? "ARES Core"}</span>
            <span>Observação ≠ causalidade</span>
          </div>
        </article>
        <article className="focus-dossier">
          <header>
            <span className="analysis-kicker">
              <CrosshairIcon aria-hidden />
              DECISÃO EM FOCO
            </span>
            <span className="dossier-index">
              01<span> / FILA</span>
            </span>
          </header>
          {focus ? (
            <>
              <div className="focus-title">
                <span className={`priority-pill p${focus.priority}`}>
                  {priorityLabels[focus.priority] ?? "Não classificada"}
                </span>
                <h2>{focus.title}</h2>
                <p>
                  {signalLabels[focus.primary_signal_type ?? ""] ??
                    focus.primary_signal_type ??
                    "Sinal não informado"}{" "}
                  <span>· {focus.external_stage ?? "Sem estágio"}</span>
                </p>
              </div>
              <div className="focus-facts">
                <div>
                  <span>Score de prioridade</span>
                  <ScoreBar
                    score={focus.score}
                    breakdown={focus.score_breakdown}
                  />
                </div>
                <div>
                  <span>Janela de ação</span>
                  <SlaCountdown timestamp={focus.sla_at} />
                </div>
              </div>
              <div className="focus-action">
                <p>
                  <ShieldCheckIcon aria-hidden />
                  Leia as evidências antes de decidir.
                </p>
                <Button asChild>
                  <Link to={`/opportunities/${focus.id}`}>
                    Analisar oportunidade
                    <ArrowUpRightIcon aria-hidden />
                  </Link>
                </Button>
              </div>
            </>
          ) : (
            <div className="focus-empty">
              <CrosshairIcon aria-hidden />
              <h2>
                {query.isError
                  ? "Aguardando conexão"
                  : query.isLoading
                    ? "Localizando prioridades"
                    : "Nenhuma decisão neste recorte"}
              </h2>
              <p>
                {query.isError
                  ? "Tente atualizar o Radar para retomar a leitura."
                  : "As oportunidades identificadas aparecerão aqui, na ordem de prioridade."}
              </p>
            </div>
          )}
          <footer>Ordem do ARES · prioridade → SLA → score</footer>
        </article>
      </section>

      <div className="section-caption">
        <span>01 / LEITURA DO CENÁRIO</span>
        <span>Distribuição atual · sem projeções</span>
      </div>

      {items.length > 0 ? (
        <Suspense fallback={<IntelligenceSkeleton />}>
          <RadarIntelligenceCharts
            analytics={analytics.data}
            freshness={analytics.dataUpdatedAt}
            source={analytics.data?.source}
            state={
              analytics.isError
                ? "error"
                : analytics.isPending
                  ? "loading"
                  : chartState
            }
            onRetry={() => void analytics.refetch()}
          />
        </Suspense>
      ) : null}

      <div className="section-caption">
        <span>02 / MESA DE DECISÃO</span>
        <span>Prioridades e evidências rastreáveis</span>
      </div>
      <section className="radar-layout">
        <div className="panel radar-table-panel">
          <div className="panel-heading radar-toolbar">
            <div>
              <span className="analysis-kicker">ONDE AGIR AGORA</span>
              <h2>Fila priorizada</h2>
              <p>Ordenação fixa: prioridade → SLA → score</p>
            </div>
            <div className="radar-filters">
              <FunnelIcon aria-hidden />
              <label>
                Estado
                <select
                  value={state}
                  onChange={(event) => {
                    setState(event.target.value);
                    resetProgressiveList();
                  }}
                >
                  <option value="">Todos</option>
                  <option value="prioritized">Priorizada</option>
                  <option value="closed">Fechada</option>
                </select>
              </label>
              <label>
                Score mínimo
                <select
                  value={minScore}
                  onChange={(event) => {
                    setMinScore(Number(event.target.value));
                    resetProgressiveList();
                  }}
                >
                  <option value={0}>Todos</option>
                  <option value={0.5}>50</option>
                  <option value={0.7}>70</option>
                  <option value={0.8}>80</option>
                </select>
              </label>
            </div>
          </div>
          {query.isLoading ? (
            <div
              className="radar-loading"
              aria-label="Carregando oportunidades"
            >
              <i />
              <i />
              <i />
              <i />
              <i />
            </div>
          ) : query.isError && !query.data ? (
            <div className="empty-state">
              <strong>Não foi possível carregar o Radar</strong>
              <span>{query.error.message}</span>
              <Button onClick={() => void query.refetch()}>
                Tentar novamente
              </Button>
            </div>
          ) : items.length === 0 ? (
            <div className="empty-state">
              <strong>Nenhuma oportunidade neste recorte</strong>
              <span>
                Ajuste os filtros ou gere um evento de risco no FakeCRM.
              </span>
              <Button
                variant="outline"
                onClick={() => {
                  setState("");
                  setMinScore(0);
                  resetProgressiveList();
                }}
              >
                Limpar filtros
              </Button>
            </div>
          ) : (
            <>
              <div
                className="radar-table-wrap well"
                ref={tableWrapRef}
                tabIndex={0}
                role="region"
                aria-label="Fila de oportunidades com rolagem"
                onScroll={(event) => {
                  const el = event.currentTarget;
                  if (
                    hasMore &&
                    el.scrollTop > 0 &&
                    el.scrollHeight - el.clientHeight - el.scrollTop < 24
                  )
                    revealNextBatch();
                }}
              >
                <table className="radar-table">
                  <thead>
                    <tr>
                      <th>Prioridade</th>
                      <th>Oportunidade</th>
                      <th>Score</th>
                      <th>SLA</th>
                      <th>Valor</th>
                      <th>
                        <span className="sr-only">Abrir</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleItems.map((item, index) => (
                      <tr
                        key={item.id}
                        className="radar-row-enter"
                        style={
                          { "--row-index": index % ROW_BATCH } as CSSProperties
                        }
                      >
                        <td>
                          <span className={`priority-pill p${item.priority}`}>
                            {priorityLabels[item.priority]}
                          </span>
                        </td>
                        <td>
                          <Link
                            className="opportunity-title"
                            to={`/opportunities/${item.id}`}
                          >
                            {item.title}
                          </Link>
                          <small>
                            {signalLabels[item.primary_signal_type ?? ""] ??
                              "Sem sinal principal"}{" "}
                            · {item.signal_count} sinais
                          </small>
                        </td>
                        <td>
                          <ScoreBar
                            score={item.score}
                            breakdown={item.score_breakdown}
                          />
                        </td>
                        <td>
                          <SlaCountdown timestamp={item.sla_at} />
                        </td>
                        <td className="tabular">
                          <LiveValue
                            value={item.deal_value}
                            format={(value) => money(value, item.currency)}
                            animateInitial={false}
                          />
                        </td>
                        <td>
                          <Link
                            className="row-link"
                            to={`/opportunities/${item.id}`}
                            aria-label={`Abrir ${item.title}`}
                          >
                            <ArrowRightIcon aria-hidden />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {hasMore ? (
                  <div
                    ref={loadMoreRef}
                    className="radar-load-sentinel"
                    aria-hidden
                  />
                ) : null}
              </div>
              <div className="radar-progressive-foot" aria-live="polite">
                <span>
                  Exibindo {visibleItems.length} de {items.length} oportunidades
                  {query.hasNextPage ? " carregadas (há mais na fila)" : ""}
                </span>
                {hasMore ? (
                  <Button
                    variant="ghost"
                    onClick={() => void revealNextBatch()}
                    disabled={query.isFetchingNextPage}
                  >
                    {query.isFetchingNextPage
                      ? "Carregando fila…"
                      : "Carregar próximas 5"}
                  </Button>
                ) : (
                  <small>Fim da fila deste recorte</small>
                )}
              </div>
            </>
          )}
          <div className="provenance queue-provenance">
            <span>
              Fonte: {query.data?.pages[0]?.source ?? "ARES Core"} · Recorte
              carregado da API
            </span>
            <Freshness timestamp={query.dataUpdatedAt} />
          </div>
        </div>
        <aside className="risk-panel">
          <RiskDistributionChart
            items={items}
            freshness={query.dataUpdatedAt}
            source={query.data?.pages[0]?.source}
            state={chartState}
            onRetry={() => void query.refetch()}
          />
          <div className="audit-note">
            <ShieldCheckIcon aria-hidden />
            <div>
              <strong>Da observação à evidência.</strong>
              <p>
                A prioridade direciona a análise. Ações dependem de Policy e
                aprovação; valor influenciado não é resultado incremental
                comprovado.
              </p>
              <Link to="/journal">
                Consultar trilha de eventos <ArrowUpRightIcon aria-hidden />
              </Link>
            </div>
          </div>
        </aside>
      </section>
      {toast ? (
        <div className="sla-toast" role="status">
          Um prazo de ação acabou de vencer. A fila foi sinalizada.
        </div>
      ) : null}
    </main>
  );
}
