import { useCallback, useMemo, useState } from "react";
import { AresChart } from "@/charts/AresChart";
import {
  ChartDataTable,
  ChartFrame,
  type ChartDatum,
  type ChartMetadata,
} from "@/charts/ChartFrame";
import { useThemeTokens } from "@/charts/aresTheme";
import { magnitudeOption } from "@/charts/magnitudeOption";
import type { ChartForm } from "@/charts/chartForms";
import { safeSum } from "@/lib/numbers";

import { money, signalLabels } from "./format";
import type { OpportunityListItem } from "./types";

/**
 * Only forms that keep the reading honest. Stages are ordered, so a funnel and a
 * line are legitimate; signals are nominal, so a funnel would invent a sequence.
 */
const STAGE_FORMS: readonly ChartForm[] = ["column", "bar", "funnel", "treemap"];
const SIGNAL_FORMS: readonly ChartForm[] = ["bar", "column", "treemap"];
const SLA_FORMS: readonly ChartForm[] = ["bar", "column", "donut"];

function groupItems(
  items: OpportunityListItem[],
  keyOf: (item: OpportunityListItem) => string,
) {
  const groups = new Map<string, OpportunityListItem[]>();
  for (const item of items) {
    const key = keyOf(item);
    const group = groups.get(key) ?? [];
    group.push(item);
    groups.set(key, group);
  }
  return [...groups].map(([label, values]) => ({ label, values }));
}

function validCurrency(value: string | null | undefined) {
  return typeof value === "string" &&
    /^[A-Z]{3}$/.test(value.trim().toUpperCase())
    ? value.trim().toUpperCase()
    : null;
}

export function RadarIntelligenceCharts({
  items,
  now,
  freshness,
  source,
  state = "ready",
  onRetry,
  partialMessage,
}: ChartMetadata & {
  items: OpportunityListItem[];
  now: number;
}) {
  const tokens = useThemeTokens();
  const [selectedCurrency, setSelectedCurrency] = useState("BRL");
  const currencies = useMemo(
    () =>
      [
        ...new Set(
          items
            .map((item) => validCurrency(item.currency))
            .filter((currency): currency is string => currency !== null),
        ),
      ].sort(),
    [items],
  );
  const currency = currencies.includes(selectedCurrency)
    ? selectedCurrency
    : (currencies[0] ?? "BRL");
  const currencyItems = useMemo(
    () => items.filter((item) => validCurrency(item.currency) === currency),
    [items, currency],
  );
  const missingCurrency = items.filter(
    (item) => validCurrency(item.currency) === null,
  ).length;
  const knownValues = useMemo(
    () => safeSum(currencyItems, "deal_value"),
    [currencyItems],
  );
  const stages = useMemo(
    () =>
      groupItems(
        currencyItems,
        (item) => item.external_stage?.trim() || "Sem etapa",
      )
        .map((group) => {
          const sum = safeSum(group.values, "deal_value");
          return {
            label: group.label,
            value: sum.valid > 0 ? sum.total : null,
            detail: sum.missing
              ? `${sum.missing} sem valor informado`
              : undefined,
          };
        })
        .sort((a, b) => (b.value ?? 0) - (a.value ?? 0)),
    [currencyItems],
  );
  const signals = useMemo(
    () =>
      groupItems(
        items,
        (item) =>
          signalLabels[item.primary_signal_type ?? ""] ??
          item.primary_signal_type ??
          "Sem sinal classificado",
      )
        .map((group) => ({ label: group.label, value: group.values.length }))
        .sort((a, b) => b.value - a.value),
    [items],
  );
  // Clock boundaries are real data transitions; no simulated activity is added.
  const slaCounts = useMemo(() => {
    const counts = [0, 0, 0, 0];
    for (const item of items) {
      const deadline = item.sla_at ? Date.parse(item.sla_at) : Number.NaN;
      const group = !Number.isFinite(deadline)
        ? 3
        : deadline <= now
          ? 0
          : deadline <= now + 86_400_000
            ? 1
            : 2;
      counts[group] += 1;
    }
    return counts;
  }, [items, now]);
  const [overdueCount, soonCount, laterCount, missingDeadlineCount] = slaCounts;
  const sla = useMemo(
    () => [
      {
        label: "Vencido",
        value: overdueCount,
        color: tokens.brasa,
        worsening: true,
      },
      {
        label: "Próximas 24h",
        value: soonCount,
        color: tokens.ambar,
        worsening: true,
      },
      { label: "Depois de 24h", value: laterCount, color: tokens.jade },
      {
        label: "Sem prazo válido",
        value: missingDeadlineCount,
        color: tokens.aco,
      },
    ],
    [overdueCount, soonCount, laterCount, missingDeadlineCount, tokens],
  );
  const signalRows: ChartDatum[] = signals;
  const stageRows: ChartDatum[] = stages;

  // Stages are ordered, so their colour is one hue in monotone steps and the
  // reader sees the funnel order in the ramp itself.
  const stageChart = useCallback(
    (form: ChartForm) => (
      <AresChart
        formKey={form}
        option={magnitudeOption(
          form,
          {
            rows: stages,
            measure: `Valor observado (${currency})`,
            format: (value) => money(value, currency),
            ordered: true,
            base: tokens.brasa,
            describe: (row) =>
              row.value === null
                ? "Sem valor válido nesta moeda."
                : `${((row.value / (knownValues.total || 1)) * 100).toFixed(1)}% do valor observado no recorte.`,
          },
          tokens,
        )}
        label={`Valor observado por etapa, em ${currency}`}
        physicalAxis={form === "column"}
      />
    ),
    [stages, tokens, currency, knownValues.total],
  );

  // Signals are nominal and the task is magnitude, so one hue: bar length is the
  // measure and the identity channel stays unspent.
  const signalChart = useCallback(
    (form: ChartForm) => (
      <AresChart
        formKey={form}
        option={magnitudeOption(
          form,
          {
            rows: signals,
            measure: "Oportunidades",
            format: (value) => `${value}`,
            base: tokens.aco,
            describe: (row) =>
              `${(((row.value ?? 0) / (items.length || 1)) * 100).toFixed(1)}% da fila entra por este sinal principal.`,
          },
          tokens,
        )}
        label="Oportunidades por sinal principal, em ordem de frequência"
      />
    ),
    [signals, tokens, items.length],
  );

  // SLA colour is reserved status, never a series hue, so each row keeps its own.
  const slaChart = useCallback(
    (form: ChartForm) => (
      <AresChart
        formKey={form}
        option={magnitudeOption(
          form,
          {
            rows: sla,
            measure: "Oportunidades",
            format: (value) => `${value}`,
            base: tokens.aco,
            describe: (row) =>
              row.label === "Vencido"
                ? "Já passou do prazo acordado; exige resposta agora."
                : row.label === "Próximas 24h"
                  ? "Vence dentro de 24 horas."
                  : row.label === "Sem prazo válido"
                    ? "O CRM não informou um prazo utilizável."
                    : "Fora da janela crítica.",
          },
          tokens,
        )}
        label="Oportunidades com SLA vencido, próximas 24h, após 24h e sem prazo válido"
      />
    ),
    [sla, tokens],
  );

  const stagePartial = knownValues.partial || missingCurrency > 0;
  const stageState =
    state === "error" || state === "loading" || state === "stale"
      ? state
      : stagePartial || state === "partial"
        ? "partial"
        : items.length === 0
          ? "empty"
          : "ready";
  const valueWarning = [
    knownValues.missing
      ? `${knownValues.missing} registro(s) em ${currency} sem valor informado.`
      : "",
    missingCurrency ? `${missingCurrency} sem moeda válida.` : "",
    stagePartial
      ? "Total parcial; valor completo indisponível."
      : partialMessage,
  ]
    .filter(Boolean)
    .join(" ");
  const metadata = {
    freshness,
    source,
    state: items.length === 0 && state === "ready" ? ("empty" as const) : state,
    onRetry,
    partialMessage,
  };

  return (
    <section className="radar-intelligence-grid" aria-label="Análises do Radar">
      <ChartFrame
        {...metadata}
        className="chart-stage"
        title="Exposição por etapa"
        definition="Onde se concentra o valor observado do recorte"
        unit={`Valor observado · ${currency}`}
        period="Fila no recorte atual"
        attribution="Observação; causalidade não demonstrada"
        state={stageState}
        partialMessage={valueWarning}
        hasData={knownValues.valid > 0}
        emptyMessage={
          items.length
            ? "Os negócios deste recorte ainda não possuem valores válidos nesta moeda."
            : "As etapas aparecem quando as oportunidades entram no Radar."
        }
        actions={
          currencies.length > 1 ? (
            <select
              className="well"
              aria-label="Moeda da análise de exposição"
              value={currency}
              onChange={(event) => setSelectedCurrency(event.target.value)}
            >
              {currencies.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          ) : undefined
        }
        forms={STAGE_FORMS}
        formKey="radar-stage"
        renderForm={stageChart}
        table={
          <ChartDataTable
            title="Exposição por etapa"
            rows={stageRows}
            unit={currency}
            format={(value) => money(value, currency)}
          />
        }
      />
      <ChartFrame
        {...metadata}
        className="chart-signals"
        title="Sinais dominantes"
        definition="O motivo principal de atenção em cada oportunidade"
        unit="Oportunidades"
        period="Fila no recorte atual"
        attribution="Sinal observado; sem causalidade"
        hasData={items.length > 0}
        forms={SIGNAL_FORMS}
        formKey="radar-signals"
        renderForm={signalChart}
        table={
          <ChartDataTable
            title="Sinais dominantes"
            rows={signalRows}
            unit="Oportunidades"
          />
        }
      />
      <ChartFrame
        {...metadata}
        className="chart-sla"
        title="Janela de SLA"
        definition="Prazos que exigem resposta e cobertura de atendimento"
        unit="Oportunidades"
        period="Agora / próximas 24 horas"
        hasData={items.length > 0}
        forms={SLA_FORMS}
        formKey="radar-sla"
        renderForm={slaChart}
        table={
          <ChartDataTable
            title="Janela de SLA"
            rows={sla}
            unit="Oportunidades"
          />
        }
      />
    </section>
  );
}
