import type { CommandCenterSummary } from "@/features/agents/contract";

const day = (offset: number) => {
  const date = new Date(Date.UTC(2026, 8, 17 - offset));
  return date.toISOString().slice(0, 10);
};
const DAYS = [3, 2, 1, 0].map(day);
const OPP = "50000000-0000-0000-0000-000000000005";
const CORR = "60000000-0000-0000-0000-000000000006";

/** Typed from the generated contract; string decimals like the API. */
export const fixture: CommandCenterSummary = {
  window: {
    since: "2026-08-18T18:29:45Z",
    until: "2026-09-17T18:29:45Z",
    days: 30,
  },
  scope: { mode: "tenant", role: "admin", owner_user_id: null },
  capabilities: { approve: true, assign: false, fix_connection: true },
  now: {
    open_at_risk: 180,
    critical: 117,
    sla_overdue: 177,
    sla_next_6h: 0,
    sla_missing: 3,
    without_owner: 180,
    awaiting_decision: 2,
    value_at_risk: [
      { currency: "BRL", total: "17591000.00", count: 180, missing: 2 },
      { currency: null, total: null, count: 3, missing: 3 },
    ],
    queue: [
      {
        opportunity_id: OPP,
        title: "Integração M2",
        state: "prioritized",
        priority: 0,
        score: "0.7790",
        sla_at: new Date(Date.now() + 3 * 3_600_000).toISOString(),
        owner_user_id: null,
        primary_signal_type: "follow_up_overdue",
        signal_count: 5,
        deal_value: null,
        currency: null,
        pending_approval_id: "70000000-0000-0000-0000-000000000007",
      },
    ],
    queue_limit: 8,
    approvals: {
      pending: 2,
      expiring_within_6h: 1,
      items_limit: 5,
      items: [
        {
          approval_id: "70000000-0000-0000-0000-000000000007",
          opportunity_id: OPP,
          title: "Integração M2",
          urgency: "critical",
          required_role: "manager",
          expires_at: new Date(Date.now() + 2 * 3_600_000).toISOString(),
          created_at: "2026-09-16T10:00:00Z",
        },
      ],
    },
    failed_actions: {
      count: 1,
      items_limit: 5,
      items: [
        {
          execution_id: "80000000-0000-0000-0000-000000000008",
          opportunity_id: OPP,
          title: "Integração M2",
          action_kind: "create_task",
          attempts: 2,
          finished_at: "2026-09-16T12:00:00Z",
          correlation_id: CORR,
        },
      ],
    },
    connections: {
      total: 2,
      degraded: 1,
      revoked: 0,
      items: [
        {
          connection_id: "90000000-0000-0000-0000-000000000009",
          provider: "fake-crm-http",
          status: "degraded",
          last_sync_at: "2026-09-12T03:06:11Z",
        },
      ],
    },
    freshness_at: "2026-09-17T03:38:00Z",
  },
  impact: {
    window: {
      since: "2026-08-18T18:29:45Z",
      until: "2026-09-17T18:29:45Z",
      days: 30,
    },
    counts: { at_risk: 180, worked: 47 },
    amounts: [
      {
        currency: "BRL",
        observations: 3,
        synthetic_observations: 3,
        sales_observed: 2,
        recovered: 1,
        sale_value: "6000.00",
        ares_influenced_value: "1200.00",
        incremental_value: null,
        freshness_at: "2026-09-16T09:00:00Z",
      },
      {
        currency: null,
        observations: 42,
        synthetic_observations: 0,
        sales_observed: 0,
        recovered: 0,
        sale_value: null,
        ares_influenced_value: null,
        incremental_value: null,
        freshness_at: null,
      },
    ],
    ai_cost: { runs: 44, measured_runs: 0, cost_usd: null },
    source: "Supabase/PostgreSQL — outcomes e trilha de intervenções",
    computed_at: "2026-09-17T18:29:45Z",
    definitions: ["Valor influenciado não prova causalidade."],
  },
  trends: {
    days: DAYS,
    series: [
      { key: "opened", label: "Abertas", values: [0, 2, 0, 1] },
      { key: "worked", label: "Trabalhadas", values: [0, 1, 0, 0] },
      { key: "executed", label: "Executadas", values: [0, 1, 0, 0] },
      { key: "failed", label: "Falhas", values: [0, 0, 1, 0] },
    ],
    freshness_at: "2026-09-16T12:00:00Z",
  },
  funnel: {
    cohort: 180,
    stages: [
      { state: "detected", label: "Detectadas", reached: 177 },
      { state: "prioritized", label: "Priorizadas", reached: 177 },
      { state: "awaiting_decision", label: "Aguardando decisão", reached: 44 },
      { state: "authorized", label: "Autorizadas", reached: 42 },
      { state: "executing", label: "Em execução", reached: 42 },
      { state: "observing", label: "Em observação", reached: 42 },
      { state: "closed", label: "Encerradas", reached: 0 },
    ],
  },
  signals: {
    total: 7,
    without_opportunity: 1,
    days: DAYS,
    types: [
      { signal_type: "follow_up_overdue", severity: 5, total: 4 },
      { signal_type: "missing_next_step", severity: 3, total: 3 },
    ],
    cells: [
      { day: DAYS[1], signal_type: "follow_up_overdue", count: 4 },
      { day: DAYS[3], signal_type: "missing_next_step", count: 3 },
    ],
    freshness_at: "2026-09-17T03:38:00Z",
  },
  heatmap: {
    total: 7,
    timezone: "UTC",
    cells: Array.from({ length: 28 }, (_, index) => ({
      weekday: Math.floor(index / 4),
      band: index % 4,
      count: index === 9 ? 7 : 0,
    })),
  },
  activity: {
    limit: 25,
    truncated: false,
    items: [
      {
        kind: "decision",
        occurred_at: "2026-09-17T10:00:00Z",
        actor_type: "human",
        opportunity_id: OPP,
        title: "Integração M2",
        label: "approved",
        detail: null,
        attribution_level: null,
        correlation_id: CORR,
      },
      {
        kind: "action",
        occurred_at: "2026-09-16T12:00:00Z",
        actor_type: "system",
        opportunity_id: OPP,
        title: "Integração M2",
        label: "succeeded",
        detail: "create_task",
        attribution_level: null,
        correlation_id: CORR,
      },
      {
        kind: "state",
        occurred_at: "2026-09-16T11:00:00Z",
        actor_type: "ares_agent",
        opportunity_id: OPP,
        title: "Integração M2",
        label: "prioritized",
        detail: "deterministic_score_available",
        attribution_level: null,
        correlation_id: CORR,
      },
      {
        kind: "outcome",
        occurred_at: "2026-09-16T09:00:00Z",
        actor_type: "system",
        opportunity_id: OPP,
        title: "Integração M2",
        label: "recovered",
        detail: null,
        attribution_level: "influenced",
        correlation_id: CORR,
      },
    ],
  },
  coverage: {
    opportunities: 180,
    opportunities_with_owner: 0,
    opportunities_with_sla: 177,
    deals_with_value: 178,
    signals_with_opportunity: 6,
    synthetic_outcomes: 3,
    ai_runs: 44,
    ai_measured_runs: 0,
  },
  definitions: [
    "open_at_risk",
    "critical",
    "sla_overdue",
    "sla_next_6h",
    "sla_missing",
    "without_owner",
    "awaiting_decision",
    "value_at_risk",
    "impact_at_risk",
    "impact_worked",
    "impact_recovered",
    "impact_sales_observed",
    "impact_sale_value",
    "impact_ares_influenced_value",
    "impact_ai_cost",
    "impact_incremental_value",
  ].map((key) => ({
    key,
    label:
      key === "critical"
        ? "Críticas"
        : key.replace(/_/g, " ").replace(/^impact /, ""),
    formula: `Fórmula sintética de ${key}.`,
    tables: ["ares_opportunities"],
    period: "Retrato na data da consulta",
    attribution_level: key.startsWith("impact_ares") ? "influenced" : null,
    attribution: "Observação operacional",
  })),
  source:
    "Supabase/PostgreSQL — oportunidades, sinais, transições, aprovações, execuções, conexões e outcomes",
  freshness_at: "2026-09-17T03:38:00Z",
  computed_at: "2026-09-17T18:29:45Z",
};
