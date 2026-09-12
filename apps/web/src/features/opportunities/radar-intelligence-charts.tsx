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
import {
  heatmapOption,
  matrixOption,
  trendOption,
} from "@/charts/analysisOptions";
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
const AGING_FORMS: readonly ChartForm[] = ["line", "area"];
const RHYTHM_FORMS: readonly ChartForm[] = ["heatmap", "column"];
const MATRIX_FORMS: readonly ChartForm[] = ["scatter"];

const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
const HOUR_BANDS = ["18–24h", "12–18h", "6–12h", "0–6h"];

/** Buckets a timestamp into the weekday column and hour-band row of the grid. */
function rhythmCell(iso: string) {
  const when = new Date(iso);
  const hour = when.getHours();
  const band = hour >= 18 ? 0 : hour >= 12 ? 1 : hour >= 6 ? 2 : 3;
  return { column: when.getDay(), row: band };
}

function startOfDay(value: number) {
  const day = new Date(value);
  day.setHours(0, 0, 0, 0);
  return day.getTime();
}

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

  // opened_at and last_activity_at exist on every row and were never plotted:
  // the Radar had no temporal dimension at all.
  const aging = useMemo(() => {
    const opened = new Map<number, number>();
    const touched = new Map<number, number>();
    for (const item of items) {
      const open = Date.parse(item.opened_at);
      if (Number.isFinite(open))
        opened.set(startOfDay(open), (opened.get(startOfDay(open)) ?? 0) + 1);
      const active = item.last_activity_at
        ? Date.parse(item.last_activity_at)
        : Number.NaN;
      if (Number.isFinite(active))
        touched.set(startOfDay(active), (touched.get(startOfDay(active)) ?? 0) + 1);
    }
    const toPoints = (source: Map<number, number>) =>
      [...source.entries()]
        .sort(([a], [b]) => a - b)
        .map(([day, count]) => [day, count] as [number, number]);
    return { opened: toPoints(opened), touched: toPoints(touched) };
  }, [items]);

  const rhythm = useMemo(() => {
    const grid = new Map<string, number>();
    for (const item of items) {
      const stamp = item.last_activity_at ?? item.opened_at;
      if (!stamp || !Number.isFinite(Date.parse(stamp))) continue;
      const { column, row } = rhythmCell(stamp);
      const key = `${column}:${row}`;
      grid.set(key, (grid.get(key) ?? 0) + 1);
    }
    return [...grid.entries()].map(([key, value]) => {
      const [column, row] = key.split(":").map(Number);
      return [column, row, value] as [number, number, number];
    });
  }, [items]);

  // score and deal_value both sit in the payload; neither was ever related.
  const matrix = useMemo(
    () =>
      currencyItems
        .filter((item) => Number.isFinite(item.deal_value))
        .map((item) => ({
          id: item.id,
          label: item.title,
          x: item.score,
          y: item.deal_value,
          color:
            item.sla_at && Date.parse(item.sla_at) <= now
              ? tokens.brasa
              : tokens.aco,
          detail:
            item.sla_at && Date.parse(item.sla_at) <= now
              ? "SLA vencido"
              : (item.external_stage ?? "Sem etapa"),
        })),
    [currencyItems, now, tokens],
  );

  const agingChart = useCallback(
    (form: ChartForm) => (
      <AresChart
        formKey={form}
        option={trendOption(
          form,
          {
            measure: "Oportunidades",
            format: (value) => `${Math.round(value)}`,
            series: [
              {
                key: "opened",
                label: "Abertas",
                color: tokens.brasa,
                points: aging.opened,
              },
              {
                key: "touched",
                label: "Com atividade",
                color: tokens.aco,
                dash: [5, 3],
                points: aging.touched,
              },
            ],
          },
          tokens,
        )}
        label="Oportunidades abertas e com atividade registrada ao longo do tempo"
      />
    ),
    [aging, tokens],
  );

  const rhythmChart = useCallback(
    (form: ChartForm) => (
      <AresChart
        formKey={form}
        option={heatmapOption(
          form,
          {
            columns: WEEKDAYS,
            rows: HOUR_BANDS,
            cells: rhythm,
            measure: "oportunidades",
            base: tokens.brasa,
          },
          tokens,
        )}
        label="Concentração de atividade por dia da semana e faixa horária"
      />
    ),
    [rhythm, tokens],
  );

  const matrixChart = useCallback(
    (form: ChartForm) => (
      <AresChart
        formKey={form}
        option={matrixOption(
          form,
          {
            points: matrix,
            xName: "Score",
            yName: `Valor (${currency})`,
            formatX: (value) => `${Math.round(value)}`,
            formatY: (value) => money(value, currency),
            divider: {
              x: 50,
              y:
                matrix.length > 0
                  ? matrix.reduce((sum, point) => sum + point.y, 0) / matrix.length
                  : 0,
              quadrant: "Score alto · valor acima da média",
            },
          },
          tokens,
        )}
        label="Relação entre score e valor do negócio, por oportunidade"
      />
    ),
    [matrix, tokens, currency],
  );

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
      <ChartFrame
        {...metadata}
        className="chart-aging"
        title="Entrada e atividade no tempo"
        definition="Quando as oportunidades abriram e quando foram tocadas"
        unit="Oportunidades por dia"
        period="Recorte carregado"
        attribution="Observação operacional; sem projeção"
        hasData={aging.opened.length > 0}
        emptyMessage="A série começa quando o recorte traz datas de abertura."
        forms={AGING_FORMS}
        formKey="radar-aging"
        renderForm={agingChart}
        table={
          <ChartDataTable
            title="Entrada e atividade no tempo"
            rows={aging.opened.map(([day, count]) => ({
              label: new Date(day).toLocaleDateString("pt-BR"),
              value: count,
            }))}
            unit="Abertas"
          />
        }
      />
      <ChartFrame
        {...metadata}
        className="chart-rhythm"
        title="Quando a atividade acontece"
        definition="Concentração por dia da semana e faixa horária"
        unit="Oportunidades"
        period="Última atividade registrada"
        attribution="Observação operacional; horário do navegador"
        hasData={rhythm.length > 0}
        emptyMessage="A grade aparece quando houver atividade datada no recorte."
        forms={RHYTHM_FORMS}
        formKey="radar-rhythm"
        renderForm={rhythmChart}
        table={
          <ChartDataTable
            title="Quando a atividade acontece"
            rows={rhythm.map(([column, row, value]) => ({
              label: `${WEEKDAYS[column]} · ${HOUR_BANDS[row]}`,
              value,
            }))}
            unit="Oportunidades"
          />
        }
      />
      <ChartFrame
        {...metadata}
        className="chart-matrix"
        title="Score contra valor"
        definition="Onde score alto e valor alto se encontram"
        unit={`Score · valor em ${currency}`}
        period="Fila no recorte atual"
        attribution="Observação; o score não prevê fechamento"
        hasData={matrix.length > 0}
        emptyMessage="A matriz aparece quando houver score e valor na mesma moeda."
        forms={MATRIX_FORMS}
        formKey="radar-matrix"
        renderForm={matrixChart}
        table={
          <ChartDataTable
            title="Score contra valor"
            rows={matrix.map((point) => ({
              label: point.label,
              value: point.y,
              detail: `Score ${Math.round(point.x)}`,
            }))}
            unit={currency}
            format={(value) => money(value, currency)}
          />
        }
      />
    </section>
  );
}
