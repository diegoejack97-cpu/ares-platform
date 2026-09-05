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
import { ArrowRightIcon, FunnelIcon, PulseIcon } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { getOpportunities } from "./api";
import { money, signalLabels, slaLabel } from "./format";
import { RiskDistributionChart } from "./risk-distribution-chart";
import { ScoreBar } from "./score-bar";
import type { OpportunityListItem } from "./types";

const RadarIntelligenceCharts = lazy(() =>
  import("./radar-intelligence-charts").then((module) => ({
    default: module.RadarIntelligenceCharts,
  })),
);

const priorityLabels = ["Crítica", "Alta", "Média", "Baixa"];
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
  const query = useQuery({
    queryKey: ["opportunities", state, minScore],
    queryFn: () =>
      getOpportunities({
        state: state || undefined,
        minScore: minScore || undefined,
      }),
    refetchInterval: 30_000,
  });
  const items = query.data?.items ?? emptyItems;
  const now = query.data ? new Date(query.data.freshness_at).getTime() : 0;
  const atRiskValue = useMemo(
    () => items.reduce((sum, item) => sum + item.deal_value, 0),
    [items],
  );
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
  const hasMore = visibleCount < items.length;

  const revealNextBatch = useCallback(() => {
    setVisibleCount((current) => Math.min(current + ROW_BATCH, items.length));
  }, [items.length]);

  useEffect(() => {
    if (!hasMore || !loadMoreRef.current || !tableWrapRef.current) return;
    if (typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) revealNextBatch();
      },
      { root: tableWrapRef.current, threshold: 0.8 },
    );
    observer.observe(loadMoreRef.current);
    return () => observer.disconnect();
  }, [hasMore, revealNextBatch, visibleCount]);

  function resetProgressiveList() {
    setVisibleCount(ROW_BATCH);
    tableWrapRef.current?.scrollTo({ top: 0 });
  }

  return (
    <main className="workspace radar-page">
      <header className="page-header radar-page-header">
        <div>
          <span className="eyebrow">
            ARES Connect · inteligência operacional
          </span>
          <h1>Radar de receita recuperável</h1>
          <p>
            Prioridade baseada em regras auditáveis e sinais observados. O
            painel orienta a próxima ação; não afirma causalidade nem receita
            incremental.
          </p>
        </div>
        <div className="radar-header-actions">
          <span className="live-status">
            <i aria-hidden /> ARES monitorando
          </span>
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

      <section className="radar-summary" aria-label="Resumo do Radar">
        <div className="metric-card metric-card-primary">
          <span>Na fila</span>
          <strong>{items.length}</strong>
          <small>oportunidades abertas no recorte</small>
          <i className="metric-depth" aria-hidden />
        </div>
        <div className="metric-card metric-card-value">
          <span>Valor observado em risco</span>
          <strong>{money(atRiskValue)}</strong>
          <small>valor dos negócios, não atribuição ARES</small>
          <i className="metric-depth" aria-hidden />
        </div>
        <div className="metric-card metric-card-critical">
          <span>SLA vencido</span>
          <strong>{overdueCount}</strong>
          <small>exigem decisão operacional imediata</small>
          <i className="metric-depth" aria-hidden />
        </div>
        <div className="metric-card metric-card-neutral">
          <span>Sem responsável</span>
          <strong>{unassignedCount}</strong>
          <small>oportunidades sem ownership atual</small>
          <i className="metric-depth" aria-hidden />
        </div>
      </section>

      {items.length > 0 ? (
        <Suspense fallback={<IntelligenceSkeleton />}>
          <RadarIntelligenceCharts items={items} now={now} />
        </Suspense>
      ) : null}

      <section className="radar-layout">
        <div className="panel radar-table-panel">
          <div className="panel-heading radar-toolbar">
            <div>
              <span className="analysis-kicker">PRÓXIMA MELHOR AÇÃO</span>
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
          ) : query.isError ? (
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
              <div className="radar-table-wrap" ref={tableWrapRef}>
                <table className="radar-table">
                  <thead>
                    <tr>
                      <th>Prioridade</th>
                      <th>Oportunidade</th>
                      <th>Sinal principal</th>
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
                          <strong>{item.title}</strong>
                          <small>
                            {item.external_stage ?? "Sem estágio"} ·{" "}
                            {item.signal_count} sinais
                          </small>
                        </td>
                        <td>
                          {signalLabels[item.primary_signal_type ?? ""] ??
                            item.primary_signal_type}
                        </td>
                        <td>
                          <ScoreBar
                            score={item.score}
                            breakdown={item.score_breakdown}
                          />
                        </td>
                        <td>
                          <span
                            className={
                              item.sla_at &&
                              new Date(item.sla_at).getTime() < now
                                ? "sla overdue"
                                : "sla"
                            }
                          >
                            {slaLabel(item.sla_at, now)}
                          </span>
                        </td>
                        <td className="tabular">
                          {money(item.deal_value, item.currency)}
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
                </span>
                {hasMore ? (
                  <Button variant="ghost" onClick={revealNextBatch}>
                    Carregar próximas 5
                  </Button>
                ) : (
                  <small>Fim da fila deste recorte</small>
                )}
              </div>
            </>
          )}
          <div className="provenance">
            Fonte: {query.data?.source ?? "ARES Core"} · Frescor:{" "}
            {query.data
              ? new Date(query.data.freshness_at).toLocaleTimeString("pt-BR")
              : "—"}
          </div>
        </div>
        <aside className="panel risk-panel">
          <div className="panel-heading">
            <div>
              <span className="analysis-kicker">SEVERIDADE</span>
              <h2>Distribuição da fila</h2>
              <p>Quantidade por prioridade</p>
            </div>
          </div>
          <RiskDistributionChart items={items} />
          <ul>
            {priorityLabels.map((label, index) => (
              <li key={label}>
                <span className={`legend-dot p${index}`} />
                {label}
                <strong>
                  {items.filter((item) => item.priority === index).length}
                </strong>
              </li>
            ))}
          </ul>
        </aside>
      </section>
    </main>
  );
}
