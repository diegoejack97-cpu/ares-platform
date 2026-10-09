import { PortfolioPanel } from "@/features/agents/portfolio-panel";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  ArrowsClockwiseIcon,
  CrosshairIcon,
  InfoIcon,
  PlayIcon,
  ReceiptIcon,
  ShieldCheckIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  MetaRow,
  NoticeBar,
  StatusBadge,
  shortId,
  type Tone,
} from "@/components/console";
import { STALE_AFTER_MS } from "@/components/live/freshness";
import { LiveValue } from "@/components/live/live-value";
import { SlaCountdown } from "@/components/live/sla-countdown";
import type { ChartState } from "@/charts/ChartFrame";
import type {
  ActivityItem,
  CommandCenterSummary,
  ImpactAmount,
  MetricDefinition,
} from "@/features/agents/contract";
import { useLiveClock, useReducedMotion } from "@/lib/live-clock";
import { ScoreBar } from "@/features/opportunities/score-bar";
import { priorityLabels, signalLabels } from "@/features/opportunities/format";
import {
  attributionLabels,
  compact,
  money,
  resultLabels,
} from "@/features/impact/format";
import { CommandCenterError, commandCenter } from "./api";
import {
  actionKindLabels,
  actionStatusLabels,
  actorLabels,
  connectionStatusLabels,
  decisionLabels,
  reasonLabels,
  roleWords,
  stateLabels,
  urgencyLabels,
} from "./labels";
import "./command-center.css";

const CommandCenterCharts = lazy(() =>
  import("./command-center-charts").then((module) => ({
    default: module.CommandCenterCharts,
  })),
);

const DAYS_KEY = "ares-cc-days";
const WINDOWS = [7, 30, 90] as const;
type CenterView = "priorities" | "results" | "evidence";
const VIEWS: { id: CenterView; label: string; description: string }[] = [
  {
    id: "priorities",
    label: "Prioridades",
    description: "Riscos, prazos e próximos negócios a tratar",
  },
  {
    id: "results",
    label: "Resultados",
    description: "Intervenções, valor observado e tendências",
  },
  {
    id: "evidence",
    label: "Histórico e critérios",
    description: "Eventos, fontes e cálculo dos indicadores",
  },
];

function storedDays(): number {
  try {
    const value = Number(localStorage.getItem(DAYS_KEY));
    return (WINDOWS as readonly number[]).includes(value) ? value : 30;
  } catch {
    return 30;
  }
}

const rawCode = (value: string | null | undefined) =>
  value ? <span className="cell-mono">{value}</span> : null;
const label = (
  map: Record<string, string>,
  value: string | null | undefined,
) => (value ? (map[value] ?? rawCode(value)) : null);

function relative(timestamp: string | null, now: number) {
  if (!timestamp) return null;
  const stamp = Date.parse(timestamp);
  if (!Number.isFinite(stamp)) return null;
  const minutes = Math.round(Math.abs(now - stamp) / 60_000);
  const text =
    minutes < 60
      ? `${minutes} min`
      : minutes < 60 * 48
        ? `${Math.round(minutes / 60)} h`
        : `${Math.round(minutes / 1440)} d`;
  return { past: stamp <= now, text };
}

const dateTime = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString("pt-BR") : "não informado";

function MetricLabel({
  k,
  children,
  definitions,
  onJump,
}: {
  k: string;
  children: React.ReactNode;
  definitions: Map<string, MetricDefinition>;
  onJump: (id: string) => void;
}) {
  const definition = definitions.get(k);
  return (
    <span className="metric-label" data-def-key={k}>
      {children}
      <button
        type="button"
        className="cc-def"
        aria-label={`Definição de ${definition?.label ?? k}`}
        title={definition?.formula}
        onClick={() => onJump(`def-${k}`)}
      >
        <InfoIcon aria-hidden />
      </button>
    </span>
  );
}

export function CommandCenterPage() {
  const [days, setDays] = useState(storedDays);
  const [activeView, setActiveView] = useState<CenterView>(() =>
    window.location.hash.startsWith("#def-") ? "evidence" : "priorities",
  );
  const [focusDefinition, setFocusDefinition] = useState<string | null>(() =>
    window.location.hash.startsWith("#def-")
      ? window.location.hash.slice(1)
      : null,
  );
  const [showDefinitions, setShowDefinitions] = useState(() =>
    window.location.hash.startsWith("#def-"),
  );
  const reduced = useReducedMotion();
  const now = useLiveClock();
  const query = useQuery({
    queryKey: ["command-center", days],
    queryFn: ({ signal }) => commandCenter(days, signal),
    retry: false,
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  });
  const error = query.error instanceof CommandCenterError ? query.error : null;
  const denied = error?.code === "access_denied";
  const data = query.isError ? undefined : query.data;
  const chartState: ChartState = query.isError
    ? "error"
    : query.isPending
      ? "loading"
      : now - query.dataUpdatedAt > STALE_AFTER_MS
        ? "stale"
        : "ready";
  const refetch = useCallback(() => void query.refetch(), [query]);
  const jumpTo = useCallback((id: string) => {
    setShowDefinitions(true);
    setFocusDefinition(id);
    setActiveView("evidence");
  }, []);
  useEffect(() => {
    if (activeView !== "evidence" || !focusDefinition || !data) return;
    const frame = requestAnimationFrame(() => {
      const id = focusDefinition;
      const element = document.getElementById(id);
      element?.scrollIntoView?.({
        block: "center",
        behavior: reduced ? "auto" : "smooth",
      });
      element?.focus({ preventScroll: true });
      setFocusDefinition(null);
    });
    return () => cancelAnimationFrame(frame);
  }, [activeView, data, focusDefinition, reduced]);
  const definitions = useMemo(
    () => new Map((data?.definitions ?? []).map((item) => [item.key, item])),
    [data],
  );
  const changeDays = (value: number) => {
    setDays(value);
    try {
      localStorage.setItem(DAYS_KEY, String(value));
    } catch {
      /* per-viewer convenience only */
    }
  };
  const scopeCopy = !data
    ? null
    : data.scope.mode === "own"
      ? "Escopo: minhas oportunidades"
      : data.scope.role === "auditor"
        ? "Escopo: toda a conta · leitura (auditor)"
        : `Escopo: toda a conta · papel ${roleWords[data.scope.role] ?? data.scope.role}`;
  const degraded = data
    ? data.now.connections.degraded + data.now.connections.revoked
    : 0;

  return (
    <main className="workspace console-page command-center-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">COMMAND CENTER</span>
          <h1>Command Center</h1>
          <p>
            Prioridades da operação, resultados observados e evidências da
            atuação do ARES.
          </p>
          {scopeCopy ? <p className="cc-scope">{scopeCopy}</p> : null}
        </div>
        <div className="toolbar">
          <div className="field">
            <label htmlFor="cc-days">Período</label>
            <select
              id="cc-days"
              value={days}
              disabled={denied}
              onChange={(event) => changeDays(Number(event.target.value))}
            >
              {WINDOWS.map((value) => (
                <option key={value} value={value}>
                  {value} dias
                </option>
              ))}
            </select>
          </div>
          <Button
            variant="outline"
            disabled={query.isFetching || denied}
            onClick={refetch}
          >
            <ArrowsClockwiseIcon aria-hidden /> Atualizar
          </Button>
        </div>
      </header>

      {error && !denied ? (
        <NoticeBar
          tone="critical"
          role="alert"
          title="Não foi possível carregar o Command Center."
          actions={
            <Button size="sm" onClick={refetch}>
              Tentar novamente
            </Button>
          }
        >
          {error.message}{" "}
          <code className="cell-mono">
            Correlação {error.correlationId ?? "não informada"}
          </code>
        </NoticeBar>
      ) : null}
      {denied ? (
        <NoticeBar tone="neutral" role="alert">
          Esta conta não tem acesso ao Command Center.
        </NoticeBar>
      ) : null}
      <PortfolioPanel />
      {data && degraded > 0 ? (
        <NoticeBar
          tone="warning"
          title="Fonte degradada."
          actions={<FixConnection enabled={data.capabilities.fix_connection} />}
        >
          {data.now.connections.items
            .map(
              (item) =>
                `${item.provider} · ${connectionStatusLabels[item.status] ?? item.status}`,
            )
            .join(" · ")}
        </NoticeBar>
      ) : null}
      {data && data.coverage.synthetic_outcomes > 0 ? (
        <NoticeBar tone="warning" title="Dados sintéticos.">
          Este relatório contém dados sintéticos de demonstração:{" "}
          {data.coverage.synthetic_outcomes} outcome(s) marcados como
          m6-synthetic-pilot.
        </NoticeBar>
      ) : null}
      {data?.scope.mode === "own" ? (
        <NoticeBar tone="info">
          Escopo próprio: apenas oportunidades sob sua responsabilidade.
          Agregados do tenant ficam com gestores.
        </NoticeBar>
      ) : null}
      {data?.scope.role === "auditor" ? (
        <NoticeBar tone="neutral">
          Leitura de auditoria: definições, fonte e cadeia disponíveis; ações
          desabilitadas.
        </NoticeBar>
      ) : null}
      {data && chartState === "stale" ? (
        <NoticeBar tone="neutral">
          Leitura com mais de 90 s. Os valores continuam disponíveis.
        </NoticeBar>
      ) : null}

      {query.isPending && !data ? <PageSkeleton /> : null}
      {data ? (
        <div className="console-stack">
          <nav className="cc-view-nav" aria-label="Áreas do Command Center">
            {VIEWS.map((view) => (
              <button
                key={view.id}
                type="button"
                className="cc-view-button"
                aria-pressed={activeView === view.id}
                onClick={() => setActiveView(view.id)}
              >
                <strong>{view.label}</strong>
                <span>{view.description}</span>
              </button>
            ))}
          </nav>
          <MetaRow
            label="Proveniência do painel"
            items={[
              [
                "Período",
                `${dateTime(data.window.since)} – ${dateTime(data.window.until)} (${data.window.days} d)`,
              ],
              ["Fonte", data.source],
              [
                "Dado mais recente",
                data.freshness_at
                  ? dateTime(data.freshness_at)
                  : "não informado",
              ],
              ["Consulta em", dateTime(data.computed_at)],
            ]}
          />
          {activeView === "priorities" ? (
            <NowBlock
              data={data}
              definitions={definitions}
              onJump={jumpTo}
              now={now}
            />
          ) : null}
          {activeView === "results" ? (
            <>
              <ImpactBlock
                data={data}
                definitions={definitions}
                onJump={jumpTo}
              />
              <Suspense
                fallback={
                  <section
                    className="cc-analysis-grid intelligence-loading"
                    aria-label="Preparando análises do Command Center"
                    aria-busy="true"
                  >
                    <i />
                    <i />
                    <i />
                    <i />
                  </section>
                }
              >
                <CommandCenterCharts
                  data={data}
                  freshness={query.dataUpdatedAt || null}
                  state={chartState}
                  onRetry={refetch}
                />
              </Suspense>
            </>
          ) : null}
          {activeView === "evidence" ? (
            <>
              <ActivityBlock data={data} now={now} />
              <DefinitionsBlock
                data={data}
                expanded={showDefinitions}
                onToggle={() => setShowDefinitions((current) => !current)}
              />
            </>
          ) : null}
        </div>
      ) : null}
    </main>
  );
}

function FixConnection({ enabled }: { enabled: boolean }) {
  if (enabled)
    return (
      <Button asChild size="sm" variant="outline">
        <Link to="/pipeline">Corrigir conexão</Link>
      </Button>
    );
  return (
    <Button
      size="sm"
      variant="outline"
      disabled
      title="Corrigir conexão só está disponível no laboratório local."
    >
      Corrigir conexão
    </Button>
  );
}

function PageSkeleton() {
  return (
    <div
      className="console-stack"
      aria-busy="true"
      aria-label="Carregando Command Center"
    >
      <div className="cc-view-nav" aria-hidden="true">
        {VIEWS.map((view) => (
          <Skeleton key={view.id} className="h-16 w-full" />
        ))}
      </div>
      <section className="panel cc-now">
        <div className="panel-heading">
          <Skeleton className="h-6 w-28" />
        </div>
        <div className="panel-body cc-now-grid">
          <div className="cc-primary-stats">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className="h-28 w-full" />
            ))}
          </div>
          <div className="cc-now-main">
            <Skeleton className="h-8 w-44" />
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

/* --------------------------------------------------------------- Agora --- */

function NowBlock({
  data,
  definitions,
  onJump,
  now,
}: {
  data: CommandCenterSummary;
  definitions: Map<string, MetricDefinition>;
  onJump: (id: string) => void;
  now: number;
}) {
  const block = data.now;
  const coverage = data.coverage;
  const [showAllQueue, setShowAllQueue] = useState(false);
  const visibleQueue = showAllQueue ? block.queue : block.queue.slice(0, 5);
  const canApprove = data.capabilities.approve;
  const approveDisabledTitle = "Aprovar exige papel gestor ou admin.";
  const assignTitle =
    "Assumir ainda não existe no ARES: não há endpoint de atribuição de responsável.";
  const stat = (
    key: string,
    title: string,
    value: number,
    badge?: React.ReactNode,
    note?: React.ReactNode,
  ) => (
    <div className="cc-stat">
      <dt>
        <MetricLabel k={key} definitions={definitions} onJump={onJump}>
          {title}
        </MetricLabel>
      </dt>
      <dd>
        <LiveValue value={value} format={compact} />
        {badge}
        {note ? <small>{note}</small> : null}
      </dd>
    </div>
  );
  return (
    <section className="panel cc-now" aria-labelledby="cc-now-h">
      <div className="panel-heading">
        <div>
          <h2 id="cc-now-h">Agora</h2>
          <p>Retrato na data da consulta.</p>
        </div>
        <div className="panel-aside">
          <Button asChild size="sm" variant="outline">
            <Link to="/radar">Ver Radar</Link>
          </Button>
        </div>
      </div>
      <div className="panel-body cc-now-grid">
        <div className="cc-now-strip">
          <dl className="cc-primary-stats">
            {stat("open_at_risk", "Abertas em risco", block.open_at_risk)}
            {stat(
              "critical",
              "Críticas (prioridade 0)",
              block.critical,
              block.critical > 0 ? (
                <StatusBadge tone="critical">crítico</StatusBadge>
              ) : null,
            )}
            {stat(
              "sla_overdue",
              "SLA vencido",
              block.sla_overdue,
              block.sla_overdue > 0 ? (
                <StatusBadge tone="critical">vencido</StatusBadge>
              ) : null,
            )}
            <div className="cc-stat cc-stat-value">
              <dt>
                <MetricLabel
                  k="value_at_risk"
                  definitions={definitions}
                  onJump={onJump}
                >
                  Valor em risco
                </MetricLabel>
              </dt>
              {block.value_at_risk.length === 0 ? (
                <dd>
                  <span className="cell-muted">
                    Nenhuma oportunidade aberta
                  </span>
                </dd>
              ) : (
                block.value_at_risk.map((row) => (
                  <dd key={row.currency ?? "none"}>
                    {row.currency === null ? (
                      <span className="cell-muted">
                        {row.count} sem moeda, fora dos totais
                      </span>
                    ) : (
                      <>
                        <strong>
                          {money(row.total, row.currency) ?? (
                            <span className="cell-muted">Não informado</span>
                          )}
                        </strong>
                        <small>
                          {row.count} negócios
                          {row.missing ? ` · ${row.missing} sem valor` : ""}
                        </small>
                      </>
                    )}
                  </dd>
                ))
              )}
            </div>
          </dl>
          <details className="cc-secondary-details">
            <summary>Ver indicadores de prazo, responsável e decisão</summary>
            <dl>
              {stat(
                "sla_next_6h",
                "Próximas 6 h",
                block.sla_next_6h,
                block.sla_next_6h > 0 ? (
                  <StatusBadge tone="warning">em 6 h</StatusBadge>
                ) : null,
              )}
              {stat(
                "sla_missing",
                "Sem prazo",
                block.sla_missing,
                null,
                `${coverage.opportunities_with_sla} de ${coverage.opportunities} abertas com prazo definido`,
              )}
              {stat(
                "without_owner",
                "Sem responsável",
                block.without_owner,
                null,
                `${coverage.opportunities_with_owner} de ${coverage.opportunities} com responsável`,
              )}
              {stat(
                "awaiting_decision",
                "Aguardando decisão",
                block.awaiting_decision,
              )}
            </dl>
            <MetaRow
              label="Proveniência do bloco Agora"
              items={[
                ["Período", "Retrato na data da consulta"],
                [
                  "Fonte",
                  "ares_opportunities, deals, approval_requests, action_executions, connections",
                ],
                [
                  "Dado mais recente",
                  block.freshness_at
                    ? dateTime(block.freshness_at)
                    : "não informado",
                ],
                ["Atribuição", "Observação operacional"],
              ]}
            />
          </details>
        </div>
        <div className="cc-now-main">
          <div className="cc-queue-head">
            <div>
              <h3>Fila prioritária</h3>
              <p>
                Negócios abertos ordenados por prioridade e prazo. Abra um caso
                para agir.
              </p>
            </div>
            <span>
              Mostrando {visibleQueue.length} de {block.queue.length}
            </span>
          </div>
          {block.queue.length === 0 ? (
            <p className="data-empty">
              {data.scope.mode === "own" && block.open_at_risk === 0
                ? "Nenhuma oportunidade está atribuída a você. O responsável vem do mapeamento de proprietário do CRM."
                : "Nenhuma oportunidade aberta neste escopo. O Radar mostra a fila completa quando novos sinais chegam."}{" "}
              <Link to="/radar">Ver Radar</Link>
            </p>
          ) : (
            <div
              className="data-table"
              role="region"
              aria-label="Fila prioritária, tabela rolável"
              tabIndex={0}
            >
              <table>
                <caption>
                  Fila prioritária — até {block.queue_limit} oportunidades
                  abertas por prioridade e prazo, na ordem do Radar
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Prioridade</th>
                    <th scope="col">Negócio</th>
                    <th scope="col">Score</th>
                    <th scope="col">SLA</th>
                    <th scope="col" className="is-numeric">
                      Valor
                    </th>
                    <th scope="col">Responsável</th>
                    <th scope="col">
                      <span className="sr-only">Ações</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visibleQueue.map((item) => (
                    <tr key={item.opportunity_id}>
                      <td data-label="Prioridade">
                        <span className={`priority-pill p${item.priority}`}>
                          {priorityLabels[item.priority] ??
                            `Prioridade ${item.priority}`}
                        </span>
                      </td>
                      <td data-label="Negócio">
                        <div className="cell-stack">
                          <Link to={`/opportunities/${item.opportunity_id}`}>
                            {item.title ?? "Sem negócio vinculado"}
                          </Link>
                          <small>
                            {item.primary_signal_type
                              ? (signalLabels[item.primary_signal_type] ??
                                item.primary_signal_type)
                              : "Sem sinal classificado"}{" "}
                            · {item.signal_count} sinais ·{" "}
                            {shortId(item.opportunity_id)}
                          </small>
                        </div>
                      </td>
                      <td data-label="Score">
                        <ScoreBar score={item.score ?? ""} breakdown={{}} />
                      </td>
                      <td data-label="SLA">
                        <SlaCountdown timestamp={item.sla_at} />
                      </td>
                      <td className="is-numeric" data-label="Valor">
                        {item.deal_value === null ? (
                          <span className="cell-muted">
                            Valor não informado
                          </span>
                        ) : (
                          money(item.deal_value, item.currency ?? "BRL")
                        )}
                      </td>
                      <td data-label="Responsável">
                        {item.owner_user_id ? (
                          <span className="cell-mono">
                            {shortId(item.owner_user_id)}
                          </span>
                        ) : (
                          <span className="cell-muted">Sem responsável</span>
                        )}
                      </td>
                      <td data-label="Ações">
                        <div className="cell-actions">
                          <Button asChild size="sm" variant="outline">
                            <Link to={`/opportunities/${item.opportunity_id}`}>
                              Abrir
                            </Link>
                          </Button>
                          {item.pending_approval_id ? (
                            canApprove ? (
                              <Button asChild size="sm">
                                <Link to="/approvals">Aprovar</Link>
                              </Button>
                            ) : (
                              <Button
                                size="sm"
                                disabled
                                title={approveDisabledTitle}
                              >
                                Aprovar
                              </Button>
                            )
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {block.queue.length > 5 ? (
            <Button
              className="cc-queue-more"
              type="button"
              size="sm"
              variant="outline"
              aria-expanded={showAllQueue}
              onClick={() => setShowAllQueue((current) => !current)}
            >
              {showAllQueue
                ? "Mostrar menos"
                : `Mostrar mais ${block.queue.length - 5} negócios`}
            </Button>
          ) : null}
          <details className="cc-work-details">
            <summary>
              Aprovações e integrações
              <span>
                {block.approvals.pending} aprovações ·{" "}
                {block.failed_actions.count} falhas
                {degradedItems(block).length
                  ? ` · ${degradedItems(block).length} conexões`
                  : ""}
              </span>
            </summary>
            <div className="cc-now-lists">
              <div className="cc-list">
                <h3>
                  Aprovações pendentes ({block.approvals.pending})
                  {block.approvals.expiring_within_6h > 0 ? (
                    <StatusBadge tone="warning">expira em breve</StatusBadge>
                  ) : null}
                </h3>
                <small className="cc-list-note">
                  {block.approvals.expiring_within_6h} expirando em 6 h
                </small>
                {block.approvals.items.length === 0 ? (
                  <p className="panel-note">
                    Nenhuma aprovação pendente. Novas recomendações que exigem
                    decisão humana aparecem aqui.
                  </p>
                ) : (
                  <ul>
                    {block.approvals.items.map((item) => {
                      const expiry = relative(item.expires_at, now);
                      const tone: Tone =
                        item.urgency === "critical"
                          ? "critical"
                          : item.urgency === "high"
                            ? "warning"
                            : "neutral";
                      return (
                        <li key={item.approval_id}>
                          <Link to={`/opportunities/${item.opportunity_id}`}>
                            {item.title ?? "Sem negócio vinculado"}
                          </Link>
                          <StatusBadge tone={tone}>
                            {label(urgencyLabels, item.urgency) ??
                              "Sem urgência"}
                          </StatusBadge>
                          <span className="cell-muted">
                            {expiry
                              ? expiry.past
                                ? `expirada há ${expiry.text}`
                                : `expira em ${expiry.text}`
                              : "sem expiração"}{" "}
                            · exige{" "}
                            {roleWords[item.required_role] ??
                              item.required_role}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
                <div className="form-actions">
                  {canApprove ? (
                    <Button asChild size="sm">
                      <Link to="/approvals">Aprovar em Aprovações</Link>
                    </Button>
                  ) : (
                    <Button size="sm" disabled title={approveDisabledTitle}>
                      Aprovar
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled
                    title={assignTitle}
                  >
                    Assumir
                  </Button>
                </div>
                <small className="cc-list-note">{assignTitle}</small>
              </div>
              <div className="cc-list">
                <h3>Ações falhas e integrações</h3>
                {block.failed_actions.count === 0 &&
                degradedItems(block).length === 0 ? (
                  <p className="panel-note">
                    Nenhuma falha registrada no período e todas as conexões
                    estão saudáveis ou configuradas. Zero falhas não comprova
                    sucesso das ações.
                  </p>
                ) : (
                  <ul>
                    {block.failed_actions.items.map((item) => (
                      <li key={item.execution_id}>
                        <StatusBadge tone="critical">
                          {label(actionKindLabels, item.action_kind) ?? "Ação"}
                        </StatusBadge>
                        <span>
                          {item.attempts} tentativa
                          {item.attempts === 1 ? "" : "s"}
                        </span>
                        {item.finished_at ? (
                          <time dateTime={item.finished_at}>
                            {dateTime(item.finished_at)}
                          </time>
                        ) : null}
                        <span className="cell-mono">
                          {shortId(item.correlation_id)}
                        </span>
                        <Link to={`/opportunities/${item.opportunity_id}`}>
                          Abrir oportunidade
                        </Link>
                      </li>
                    ))}
                    {degradedItems(block).map((item) => {
                      const sync = relative(item.last_sync_at, now);
                      return (
                        <li key={item.connection_id}>
                          <strong>{item.provider}</strong>
                          <StatusBadge tone="critical">
                            {connectionStatusLabels[item.status] ?? item.status}
                          </StatusBadge>
                          <span className="cell-muted">
                            {sync
                              ? `última sincronização há ${sync.text}`
                              : "nunca sincronizou"}
                          </span>
                          <FixConnection
                            enabled={data.capabilities.fix_connection}
                          />
                        </li>
                      );
                    })}
                  </ul>
                )}
                {block.failed_actions.count >
                block.failed_actions.items.length ? (
                  <small className="cc-list-note">
                    Mostrando {block.failed_actions.items.length} de{" "}
                    {block.failed_actions.count} falhas no período.
                  </small>
                ) : null}
              </div>
            </div>
          </details>
        </div>
      </div>
    </section>
  );
}

const degradedItems = (block: CommandCenterSummary["now"]) =>
  block.connections.items;

/* ------------------------------------------------------------- Impacto --- */

function ImpactBlock({
  data,
  definitions,
  onJump,
}: {
  data: CommandCenterSummary;
  definitions: Map<string, MetricDefinition>;
  onJump: (id: string) => void;
}) {
  const impact = data.impact;
  const currencies = impact.amounts
    .map((amount) => amount.currency)
    .filter((currency): currency is string => currency !== null);
  const [currency, setCurrency] = useState<string | null>(null);
  const selected = currency ?? currencies[0] ?? null;
  const amount: ImpactAmount | undefined = impact.amounts.find(
    (row) => row.currency === selected,
  );
  const withoutCurrency = impact.amounts.find((row) => row.currency === null);
  const own = data.scope.mode === "own";
  const item = (
    key: string,
    title: string,
    value: React.ReactNode,
    note: React.ReactNode,
  ) => (
    <li>
      <MetricLabel k={key} definitions={definitions} onJump={onJump}>
        {title}
      </MetricLabel>
      <strong className="metric-value">{value}</strong>
      <small className="metric-note">{note}</small>
    </li>
  );
  const muted = (text: string) => <span className="cell-muted">{text}</span>;
  return (
    <section className="panel cc-impact" aria-labelledby="cc-impact-h">
      <div className="panel-heading">
        <div>
          <h2 id="cc-impact-h">Impacto ARES</h2>
          <p>
            Último outcome por oportunidade no período, separado por moeda.
            Influência não é causalidade.
          </p>
        </div>
        <div className="panel-aside">
          {currencies.length > 1 ? (
            <select
              className="well"
              aria-label="Moeda do impacto"
              value={selected ?? ""}
              onChange={(event) => setCurrency(event.target.value)}
            >
              {currencies.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          ) : null}
          {!own ? (
            <Button asChild size="sm" variant="outline">
              <Link to="/impact">Abrir Impacto ARES</Link>
            </Button>
          ) : null}
        </div>
      </div>
      <ul className="metric-strip">
        {item(
          "impact_at_risk",
          "Em risco identificadas",
          compact(impact.counts.at_risk),
          "Observado · retrato",
        )}
        {item(
          "impact_worked",
          "Trabalhadas",
          compact(impact.counts.worked),
          "Observado · período",
        )}
        {amount ? (
          <>
            {item(
              "impact_recovered",
              "Recuperadas",
              compact(amount.recovered),
              "Observado · result_type = recovered",
            )}
            {item(
              "impact_sales_observed",
              "Vendas após intervenção",
              compact(amount.sales_observed),
              "Observado · sequência temporal, não causalidade",
            )}
            {item(
              "impact_sale_value",
              "Valor vendido",
              money(amount.sale_value, amount.currency) ??
                muted("Não informado"),
              "Observado",
            )}
            {item(
              "impact_ares_influenced_value",
              "Valor influenciado",
              money(amount.ares_influenced_value, amount.currency) ??
                muted("Atribuição indisponível"),
              <>
                <StatusBadge tone="info">influenciado</StatusBadge> não prova
                causalidade
              </>,
            )}
          </>
        ) : null}
        {item(
          "impact_ai_cost",
          "Custo de IA (USD)",
          impact.ai_cost === null || impact.ai_cost === undefined
            ? muted("Indisponível no escopo próprio")
            : impact.ai_cost.cost_usd === null
              ? muted("Não informado")
              : `USD ${Number(impact.ai_cost.cost_usd).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`,
          impact.ai_cost
            ? `${impact.ai_cost.measured_runs} de ${impact.ai_cost.runs} execuções com custo medido`
            : "Medição por tenant",
        )}
        {amount
          ? item(
              "impact_incremental_value",
              "Incremental comprovado",
              amount.incremental_value === null ? (
                <StatusBadge tone="neutral">Não comprovado</StatusBadge>
              ) : (
                money(amount.incremental_value, amount.currency)
              ),
              amount.incremental_value === null ? (
                "sem método e evidência registrados"
              ) : (
                <StatusBadge tone="good">incremental comprovado</StatusBadge>
              ),
            )
          : null}
      </ul>
      <div className="panel-body cc-impact-foot">
        {!amount ? (
          <p className="data-empty">
            Nenhum outcome observado no período. Outcomes são registrados quando
            uma intervenção é acompanhada até o resultado.
          </p>
        ) : null}
        {amount && amount.synthetic_observations > 0 ? (
          <p className="metric-coverage">
            {amount.synthetic_observations} de {amount.observations} observações
            sintéticas
          </p>
        ) : null}
        {withoutCurrency ? (
          <p className="metric-coverage">
            {withoutCurrency.observations} outcomes sem moeda, fora dos totais
          </p>
        ) : null}
        <MetaRow
          label="Proveniência do bloco Impacto"
          items={[
            [
              "Período",
              `${dateTime(impact.window.since)} – ${dateTime(impact.window.until)} (${impact.window.days} d)`,
            ],
            ["Fonte", impact.source],
            [
              "Dado mais recente",
              amount?.freshness_at
                ? dateTime(amount.freshness_at)
                : dateTime(impact.computed_at),
            ],
            ["Atribuição", "Ver rótulo de cada valor"],
          ]}
        />
      </div>
    </section>
  );
}

/* ----------------------------------------------------------- Atividade --- */

function activityIcon(item: ActivityItem) {
  if (item.kind === "state") return <CrosshairIcon aria-hidden />;
  if (item.kind === "decision") return <ShieldCheckIcon aria-hidden />;
  if (item.kind === "action")
    return item.label === "failed" ? (
      <WarningIcon aria-hidden />
    ) : (
      <PlayIcon aria-hidden />
    );
  return <ReceiptIcon aria-hidden />;
}

function activityBadge(item: ActivityItem) {
  if (item.kind === "state") {
    const tone: Tone =
      item.label === "awaiting_decision"
        ? "warning"
        : item.label === "closed"
          ? "neutral"
          : "info";
    return (
      <StatusBadge tone={tone}>
        {label(stateLabels, item.label) ?? "Estado"}
      </StatusBadge>
    );
  }
  if (item.kind === "decision") {
    const tone: Tone =
      item.label === "approved"
        ? "good"
        : item.label === "rejected"
          ? "critical"
          : "info";
    return (
      <StatusBadge tone={tone}>
        {label(decisionLabels, item.label) ?? "Decisão"}
      </StatusBadge>
    );
  }
  if (item.kind === "action") {
    return (
      <>
        <StatusBadge tone={item.label === "failed" ? "critical" : "good"}>
          {label(actionStatusLabels, item.label) ?? "Ação"}
        </StatusBadge>
        {label(actionKindLabels, item.detail)}
      </>
    );
  }
  return (
    <>
      <StatusBadge tone="info">
        {label(resultLabels, item.label) ?? "Outcome"}
      </StatusBadge>
      {item.attribution_level ? (
        <StatusBadge tone="neutral">
          {label(attributionLabels, item.attribution_level)}
        </StatusBadge>
      ) : null}
    </>
  );
}

function ActivityBlock({
  data,
  now,
}: {
  data: CommandCenterSummary;
  now: number;
}) {
  const activity = data.activity;
  const [showAll, setShowAll] = useState(false);
  const visibleItems = showAll ? activity.items : activity.items.slice(0, 5);
  void now;
  return (
    <section className="panel cc-activity" aria-labelledby="cc-activity-h">
      <div className="panel-heading">
        <div>
          <h2 id="cc-activity-h">Trilha recente</h2>
          <p>
            Mudanças de estado, decisões, execuções e outcomes do período, com a
            correlação de cada cadeia.
          </p>
        </div>
      </div>
      {activity.items.length === 0 ? (
        <p className="data-empty">
          Nenhuma decisão, intervenção ou outcome no período. A trilha registra
          cada passo feito pelo motor ou por pessoas.
        </p>
      ) : (
        <ol className="event-trail">
          {visibleItems.map((item, index) => (
            <li
              className="event-trail-item"
              key={`${item.kind}-${item.correlation_id}-${index}`}
            >
              <time dateTime={item.occurred_at}>
                {new Date(item.occurred_at).toLocaleString("pt-BR", {
                  day: "2-digit",
                  month: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </time>
              {activityIcon(item)}
              <div className="event-trail-copy">
                {activityBadge(item)}
                <span className="cell-muted">
                  {label(actorLabels, item.actor_type)}
                </span>
                {item.opportunity_id ? (
                  <Link to={`/opportunities/${item.opportunity_id}`}>
                    {item.title ?? "Sem negócio vinculado"}
                  </Link>
                ) : null}
                {item.kind === "state" && item.detail ? (
                  <span className="cell-muted">
                    {label(reasonLabels, item.detail)}
                  </span>
                ) : null}
                {item.kind !== "state" &&
                item.kind !== "action" &&
                item.detail ? (
                  <span className="cell-muted">{item.detail}</span>
                ) : null}
                {item.correlation_id ? (
                  <span className="cell-mono">
                    {shortId(item.correlation_id)}
                  </span>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
      {activity.items.length > 5 ? (
        <div className="cc-activity-more">
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-expanded={showAll}
            onClick={() => setShowAll((current) => !current)}
          >
            {showAll
              ? "Mostrar menos eventos"
              : `Mostrar mais ${activity.items.length - 5} eventos`}
          </Button>
        </div>
      ) : null}
      <footer className="panel-footer">
        <span>
          {activity.truncated
            ? `Mostrando ${visibleItems.length} dos ${activity.limit} mais recentes`
            : `Mostrando ${visibleItems.length} de ${activity.items.length} evento${activity.items.length === 1 ? "" : "s"} no período`}
        </span>
        <span className="pager">
          <Button asChild size="sm" variant="outline">
            <Link to="/journal">Abrir Event Journal</Link>
          </Button>
        </span>
        <span>Consulta em {dateTime(data.computed_at)}</span>
      </footer>
    </section>
  );
}

/* ---------------------------------------------------------- Definições --- */

function DefinitionsBlock({
  data,
  expanded,
  onToggle,
}: {
  data: CommandCenterSummary;
  expanded: boolean;
  onToggle: () => void;
}) {
  const coverage = data.coverage;
  return (
    <section className="panel cc-definitions" aria-labelledby="cc-def-h">
      <div className="panel-heading">
        <div>
          <h2 id="cc-def-h">Definições e limitações</h2>
          <p>Fórmulas, fontes e limites do cálculo retornados pelo serviço.</p>
        </div>
        <div className="panel-aside">
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-expanded={expanded}
            aria-controls="cc-definitions-content"
            onClick={onToggle}
          >
            {expanded ? "Ocultar critérios" : "Ver critérios e fórmulas"}
          </Button>
        </div>
      </div>
      {expanded ? (
        <div className="panel-body" id="cc-definitions-content">
          <ul className="definition-list">
            {data.definitions.map((definition) => (
              <li
                id={`def-${definition.key}`}
                key={definition.key}
                tabIndex={-1}
              >
                <strong>{definition.label}</strong>{" "}
                {definition.attribution_level ? (
                  <StatusBadge tone="neutral">
                    {attributionLabels[definition.attribution_level] ??
                      definition.attribution_level}
                  </StatusBadge>
                ) : null}{" "}
                — {definition.formula}{" "}
                <span className="cell-muted">
                  Fonte: {definition.tables.join(", ")} · Período:{" "}
                  {definition.period} · Atribuição: {definition.attribution}
                </span>
              </li>
            ))}
          </ul>
          <h3>Impacto ARES (texto do serviço)</h3>
          <ul className="definition-list">
            {data.impact.definitions.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
          <h3>Limitações desta leitura</h3>
          <ul className="definition-list">
            <li>
              {coverage.opportunities_with_owner} de {coverage.opportunities}{" "}
              oportunidades abertas com responsável definido.
            </li>
            <li>
              {coverage.deals_with_value} de {coverage.opportunities} com valor
              de negócio informado.
            </li>
            {coverage.ai_runs !== null ? (
              <li>
                {coverage.ai_measured_runs} de {coverage.ai_runs} execuções com
                custo medido.
              </li>
            ) : null}
            <li>Horários agregados em UTC; não há fuso por tenant.</li>
            <li>
              Nenhuma meta ou alvo é exibido: o documento-fonte não define metas
              comerciais.
            </li>
            <li>
              Aprovar e assumir acontecem nas telas de Aprovações/Oportunidade;
              este painel não executa mutações e "Assumir" ainda não tem
              endpoint.
            </li>
            <li>
              Influência não é causalidade; incremental só existe com
              attribution_level = incremental_proven e método registrado.
            </li>
          </ul>
          <h3>O que este painel não mostra</h3>
          <ul className="definition-list">
            <li>
              Metas e bullet charts: o documento-fonte não define alvos
              comerciais.
            </li>
            <li>
              Ranking de equipe: não há dado que sustente a comparação com
              honestidade.
            </li>
            <li>Funil de etapas do CRM: ver Radar › Exposição por etapa.</li>
            <li>
              Totais entre moedas: cada moeda é apresentada separadamente.
            </li>
            <li>Grafo relacional e memória semântica: fora deste recorte.</li>
          </ul>
        </div>
      ) : null}
      <footer className="panel-footer">
        <span>{data.source}</span>
        <span>Consulta em {dateTime(data.computed_at)}</span>
      </footer>
    </section>
  );
}
