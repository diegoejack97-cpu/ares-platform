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
import { finiteNumber } from "@/lib/numbers";

import { money, signalLabels } from "./format";
import type { OpportunityAnalytics } from "./types";

/**
 * Only forms that keep the reading honest. Stages are ordered, so a funnel and a
 * treemap are legitimate; signals are nominal, so a funnel would invent a sequence.
 */
const STAGE_FORMS: readonly ChartForm[] = [
  "column",
  "bar",
  "funnel",
  "treemap",
];
const SIGNAL_FORMS: readonly ChartForm[] = ["bar", "column", "treemap"];
const SLA_FORMS: readonly ChartForm[] = ["bar", "column", "donut"];
const AGING_FORMS: readonly ChartForm[] = ["line", "area"];
const RHYTHM_FORMS: readonly ChartForm[] = ["heatmap", "column"];
const MATRIX_FORMS: readonly ChartForm[] = ["scatter"];

const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
const HOUR_BANDS = ["18–24h", "12–18h", "6–12h", "0–6h"];

/** The CRM owns these names; ARES only presents them. */
const stageLabels: Record<string, string> = {
  new: "Entrada",
  qualification: "Qualificação",
  proposal: "Proposta",
  negotiation: "Negociação",
  won: "Ganho",
  lost: "Perdido",
};

export function RadarIntelligenceCharts({
  analytics,
  freshness,
  source,
  state = "ready",
  onRetry,
  partialMessage,
}: ChartMetadata & {
  analytics: OpportunityAnalytics | undefined;
}) {
  const tokens = useThemeTokens();
  const [selectedCurrency, setSelectedCurrency] = useState("BRL");
  const currencies = useMemo(
    () =>
      [
        ...new Set(
          (analytics?.stages ?? []).map((row) => row.currency).filter(Boolean),
        ),
      ].sort(),
    [analytics],
  );
  const currency = currencies.includes(selectedCurrency)
    ? selectedCurrency
    : (currencies[0] ?? "BRL");

  const stages = useMemo(
    () =>
      (analytics?.stages ?? [])
        .filter((row) => row.currency === currency)
        .map((row) => ({
          label: stageLabels[row.label] ?? row.label,
          value: finiteNumber(row.total),
          detail: row.missing
            ? `${row.missing} sem valor informado`
            : undefined,
        }))
        .sort((a, b) => (b.value ?? 0) - (a.value ?? 0)),
    [analytics, currency],
  );
  const knownValues = useMemo(() => {
    const sum = stages.reduce((acc, row) => acc + (row.value ?? 0), 0);
    const missing = (analytics?.stages ?? []).reduce(
      (acc, row) => acc + row.missing,
      0,
    );
    return { total: sum, missing, valid: stages.length, partial: missing > 0 };
  }, [stages, analytics]);
  const missingCurrency = 0;

  const signals = useMemo(
    () =>
      (analytics?.signals ?? []).map((row) => ({
        label: signalLabels[row.label] ?? row.label,
        value: row.count,
      })),
    [analytics],
  );

  const sla = useMemo(() => {
    const byBucket = new Map(
      (analytics?.sla ?? []).map((row) => [row.bucket, row.count]),
    );
    return [
      {
        label: "Vencido",
        value: byBucket.get("overdue") ?? 0,
        color: tokens.brasa,
        worsening: true,
      },
      {
        label: "Próximas 24h",
        value: byBucket.get("soon") ?? 0,
        color: tokens.ambar,
        worsening: true,
      },
      {
        label: "Depois de 24h",
        value: byBucket.get("later") ?? 0,
        color: tokens.jade,
      },
      {
        label: "Sem prazo válido",
        value: byBucket.get("missing") ?? 0,
        color: tokens.aco,
      },
    ];
  }, [analytics, tokens]);

  const aging = useMemo(
    () => ({
      opened: (analytics?.opened ?? []).map(
        (row) => [Date.parse(row.day), row.count] as [number, number],
      ),
      touched: (analytics?.activity ?? []).map(
        (row) => [Date.parse(row.day), row.count] as [number, number],
      ),
    }),
    [analytics],
  );

  const rhythm = useMemo(
    () =>
      (analytics?.rhythm ?? []).map(
        // Postgres bands hours 0..23 into 0..3 ascending; the grid reads top-down.
        (row) =>
          [row.weekday, 3 - row.band, row.count] as [number, number, number],
      ),
    [analytics],
  );

  const matrix = useMemo(
    () =>
      (analytics?.points ?? [])
        .filter((point) => point.currency === currency)
        .map((point) => {
          const value = finiteNumber(point.deal_value);
          const score = finiteNumber(point.score);
          if (value === null || score === null) return null;
          return {
            id: point.id,
            label: point.title,
            x: score * 100,
            y: value,
            color: point.overdue ? tokens.brasa : tokens.aco,
            detail: point.overdue
              ? `SLA vencido · ${stageLabels[point.stage] ?? point.stage}`
              : (stageLabels[point.stage] ?? point.stage),
          };
        })
        .filter((point): point is NonNullable<typeof point> => point !== null),
    [analytics, currency, tokens],
  );

  /** Money is skewed, so the split uses the median rather than the mean. */
  const medianValue = useMemo(() => {
    if (matrix.length === 0) return 0;
    const sorted = matrix.map((point) => point.y).sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 === 0
      ? (sorted[middle - 1] + sorted[middle]) / 2
      : sorted[middle];
  }, [matrix]);

  const signalRows: ChartDatum[] = signals;
  const stageRows: ChartDatum[] = stages;

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
              y: medianValue,
              quadrant: "Score alto · valor acima da mediana",
            },
          },
          tokens,
        )}
        label="Relação entre score e valor do negócio, por oportunidade"
      />
    ),
    [matrix, medianValue, tokens, currency],
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
              `${(((row.value ?? 0) / (analytics?.total || 1)) * 100).toFixed(1)}% da fila entra por este sinal principal.`,
          },
          tokens,
        )}
        label="Oportunidades por sinal principal, em ordem de frequência"
      />
    ),
    [signals, tokens, analytics],
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
        : (analytics?.total ?? 0) === 0
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
    state:
      (analytics?.total ?? 0) === 0 && state === "ready"
        ? ("empty" as const)
        : state,
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
          (analytics?.total ?? 0) > 0
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
        hasData={(analytics?.total ?? 0) > 0}
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
        hasData={(analytics?.total ?? 0) > 0}
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
              id: point.id,
              label: point.label,
              value: point.y,
              detail: `Score ${Math.round(point.x)} de 100`,
            }))}
            unit={currency}
            format={(value) => money(value, currency)}
          />
        }
      />
    </section>
  );
}
