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
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Freshness } from "@/components/live/freshness";
import { LiveValue } from "@/components/live/live-value";
import { SlaCountdown } from "@/components/live/sla-countdown";
import { useLiveClock } from "@/lib/live-clock";
import { safeSum } from "@/lib/numbers";
import { getOpportunities } from "./api";
import { money, signalLabels } from "./format";
import { RiskDistributionChart } from "./risk-distribution-chart";
import { ScoreBar } from "./score-bar";
import type { OpportunityListItem } from "./types";
import "./radar-v2.css";

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
    placeholderData: keepPreviousData,
    structuralSharing: true,
    refetchInterval: 15_000,
  });
  const items = query.data?.items ?? emptyItems;
  const now = useLiveClock();
  const atRiskValue = useMemo(
    () => safeSum(items.filter(item => (item.currency || "BRL") === "BRL"), "deal_value"),
    [items],
  );
  const otherCurrencies = useMemo(() => [...new Set(items.map(item => item.currency).filter(currency => currency && currency !== "BRL"))], [items]);
  const [toast, setToast] = useState(false);
  useEffect(() => {
    let timeout: ReturnType<typeof setTimeout>;
    const notify = () => { setToast(true); clearTimeout(timeout); timeout = setTimeout(() => setToast(false), 5_000); };
    window.addEventListener("ares:sla-overdue", notify);
    return () => { window.removeEventListener("ares:sla-overdue", notify); clearTimeout(timeout); };
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
  const hasMore = visibleCount < items.length;

  const revealNextBatch = useCallback(() => {
    setVisibleCount((current) => Math.min(current + ROW_BATCH, items.length));
  }, [items.length]);

  useEffect(() => {
    if (!hasMore || !loadMoreRef.current || !tableWrapRef.current) return;
    if (typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && (tableWrapRef.current?.scrollTop ?? 0) > 0) revealNextBatch();
      },
      { root: tableWrapRef.current, threshold: 0.8 },
    );
    observer.observe(loadMoreRef.current);
    return () => observer.disconnect();
  }, [hasMore, revealNextBatch, visibleCount]);

  function resetProgressiveList() {
    setVisibleCount(ROW_BATCH);
    if(tableWrapRef.current) tableWrapRef.current.scrollTop = 0;
  }

  return (
    <main className="workspace radar-page radar-v2">
      <header className="page-header radar-page-header">
        <div>
          <span className="eyebrow">
            ARES Connect · inteligência operacional
          </span>
          <h1>Radar ARES <small className="heading-index">01</small></h1>
          <p>
            Onde agir agora. Sinais, exposição comercial e prioridades em uma leitura contínua do seu CRM.
          </p>
        </div>
        <div className="radar-header-actions">
          <Freshness timestamp={query.dataUpdatedAt} />
          <Button
            variant="outline"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
          >
            <PulseIcon aria-hidden />{" "}
            {query.isFetching ? "Atualizando" : "Atualizar radar"}
          </Button>
          {items[0] ? <Button asChild><Link to={`/opportunities/${items[0].id}`}>Próxima ação <ArrowRightIcon aria-hidden /></Link></Button> : null}
        </div>
      </header>

      {query.isError && query.data ? <div className="route-status" role="alert">A atualização falhou. Exibindo a última leitura bem-sucedida.<Button variant="outline" onClick={() => void query.refetch()}>Tentar novamente</Button></div> : null}
      <section className="radar-summary" aria-label="Resumo do Radar">
        <div className="metric-card metric-card-primary">
          <span>Na fila</span>
          <strong><LiveValue value={items.length} /></strong>
          <small>oportunidades abertas no recorte</small>
        </div>
        <div className="metric-card metric-card-value">
          <span className="analysis-kicker">EXPOSIÇÃO COMERCIAL OBSERVADA</span>
          <span className="exposure-label">Valor observado em risco · BRL</span>
          <strong>{atRiskValue.valid ? <LiveValue value={atRiskValue.total} format={money} /> : "Valor não informado"}</strong>
          <small>Valor dos negócios neste recorte. O painel não afirma causalidade nem receita incremental.</small>
          {atRiskValue.partial ? <p className="partial-note">Total parcial: {atRiskValue.missing} registros sem valor válido excluídos. O valor completo não está disponível.</p> : null}
          {otherCurrencies.map(currency => { const total = safeSum(items.filter(item => item.currency === currency), "deal_value"); return <p className="partial-note" key={currency}>{currency}: {total.valid ? money(total.total, currency) : "valor não informado"}{total.partial ? ` · ${total.missing} valores ausentes` : ""}. Moedas apresentadas separadamente.</p>; })}
          <div className="exposure-foot">Fonte: {query.data?.source ?? "ARES Core"} · Recorte atual da API · Associação</div>
        </div>
        <div className="metric-card metric-card-critical">
          <span>SLA vencido</span>
          <strong><LiveValue value={overdueCount} worsening /></strong>
          <small>exigem decisão operacional imediata</small>
        </div>
        <div className="metric-card metric-card-neutral">
          <span>Sem responsável</span>
          <strong><LiveValue value={unassignedCount} worsening /></strong>
          <small>oportunidades sem ownership atual</small>
        </div>
      </section>

      {items.length > 0 ? (
        <Suspense fallback={<IntelligenceSkeleton />}>
          <RadarIntelligenceCharts items={items} now={now} freshness={query.dataUpdatedAt} state={query.isError ? "error" : "ready"} onRetry={() => void query.refetch()} />
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
              <div className="radar-table-wrap well" ref={tableWrapRef} tabIndex={0} role="region" aria-label="Fila de oportunidades com rolagem" onScroll={event => {const el=event.currentTarget; if(hasMore && el.scrollTop > 0 && el.scrollHeight-el.clientHeight-el.scrollTop < 24) revealNextBatch();}}>
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
                          <Link className="opportunity-title" to={`/opportunities/${item.id}`}>{item.title}</Link>
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
                          <SlaCountdown timestamp={item.sla_at} />
                        </td>
                        <td className="tabular">
                          <LiveValue value={item.deal_value} format={value => money(value,item.currency)} animateInitial={false} />
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
          <div className="provenance queue-provenance">
            <span>Fonte: {query.data?.source ?? "ARES Core"} · Recorte carregado da API</span><Freshness timestamp={query.dataUpdatedAt} />
          </div>
        </div>
        <aside className="risk-panel">
          <RiskDistributionChart items={items} freshness={query.dataUpdatedAt} />
          <div className="reading-guide s1"><span className="analysis-kicker">LEITURA EXPLICÁVEL</span><h2>Do sinal à próxima ação.</h2><p>Cada prioridade abre uma cadeia de evidências, contexto, recomendação e decisão humana.</p><ol><li><span>01</span>Identificar os sinais</li><li><span>02</span>Compreender a urgência</li><li><span>03</span>Decidir e acompanhar</li></ol></div>
        </aside>
      </section>
      {toast ? <div className="sla-toast" role="status">Um prazo de ação acabou de vencer. A fila foi sinalizada.</div> : null}
    </main>
  );
}
