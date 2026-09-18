import { useCallback, useMemo } from "react";
import { AresChart } from "@/charts/AresChart";
import {
  heatmapOption,
  stackedOption,
  trendOption,
} from "@/charts/analysisOptions";
import { useThemeTokens } from "@/charts/aresTheme";
import type { ChartForm } from "@/charts/chartForms";
import {
  ChartDataTable,
  ChartFrame,
  ChartLegend,
  type ChartState,
} from "@/charts/ChartFrame";
import { magnitudeOption } from "@/charts/magnitudeOption";
import type { CommandCenterSummary } from "@/features/agents/contract";
import { signalLabels } from "@/features/opportunities/format";
import { HOUR_BANDS, WEEKDAYS, signalTones } from "./labels";

const TREND_FORMS: readonly ChartForm[] = ["line", "area"];
const FUNNEL_FORMS: readonly ChartForm[] = ["funnel", "column", "bar"];
const SIGNAL_FORMS: readonly ChartForm[] = ["column", "bar"];
const HEAT_FORMS: readonly ChartForm[] = ["heatmap", "column"];

const count = (value: number) => `${Math.round(value)}`;
const shortDay = (day: string) => {
  const [, month, date] = day.split("-");
  return `${date}/${month}`;
};

export function CommandCenterCharts({
  data,
  freshness,
  state,
  onRetry,
}: {
  data: CommandCenterSummary;
  freshness: number | null;
  state: ChartState;
  onRetry: () => void;
}) {
  const tokens = useThemeTokens();
  const days = data.window.days;
  const period = `Últimos ${days} dias · até ${new Date(data.window.until).toLocaleDateString("pt-BR")} · UTC`;
  const metadata = {
    source: data.source,
    freshness,
    onRetry,
    period,
    attribution: "Observação operacional",
  };
  const passthrough =
    state === "error" || state === "loading" || state === "stale";
  const frameState = (partial: boolean, empty: boolean): ChartState =>
    passthrough ? state : empty ? "empty" : partial ? "partial" : "ready";

  /* ---------------------------------------------------------- trends --- */
  const trends = data.trends;
  const trendTotals = useMemo(
    () =>
      Object.fromEntries(
        trends.series.map((entry) => [
          entry.key,
          entry.values.reduce((sum, value) => sum + value, 0),
        ]),
      ) as Record<string, number>,
    [trends],
  );
  const trendHasData = Object.values(trendTotals).some((total) => total > 0);
  const trendChart = useCallback(
    (form: ChartForm) => {
      const styles: Record<string, { color: string; dash?: number[] }> = {
        opened: { color: tokens.brasa },
        worked: { color: tokens.aco, dash: [5, 3] },
        executed: { color: tokens.jade, dash: [2, 3] },
        failed: { color: tokens.ambar, dash: [8, 3, 2, 3] },
      };
      return (
        <AresChart
          formKey={form}
          option={trendOption(
            form,
            {
              measure: "Oportunidades",
              format: count,
              series: trends.series.map((entry) => ({
                key: entry.key,
                label: entry.label,
                color: styles[entry.key]?.color ?? tokens.aco,
                dash: styles[entry.key]?.dash,
                points: trends.days.map((day, index) => [
                  Date.parse(`${day}T00:00:00Z`),
                  entry.values[index] ?? 0,
                ]),
              })),
            },
            tokens,
          )}
          label="Abertas, trabalhadas, executadas e falhas por dia"
        />
      );
    },
    [trends, tokens],
  );

  /* ---------------------------------------------------------- funnel --- */
  const funnel = data.funnel;
  const funnelRows = useMemo(
    () =>
      funnel.stages.map((stage) => ({
        id: stage.state,
        label: stage.label,
        value: stage.reached,
        detail: `de ${funnel.cohort}`,
      })),
    [funnel],
  );
  const missingDetected = funnel.cohort - (funnel.stages[0]?.reached ?? 0);
  const funnelChart = useCallback(
    (form: ChartForm) => (
      <AresChart
        formKey={form}
        option={magnitudeOption(
          form,
          {
            rows: funnelRows,
            measure: "Oportunidades da coorte",
            format: count,
            ordered: true,
            base: tokens.brasa,
            describe: (row) =>
              `${funnel.cohort ? Math.round(((row.value ?? 0) / funnel.cohort) * 100) : 0}% da coorte de ${funnel.cohort} abertas no período`,
          },
          tokens,
        )}
        label="Oportunidades da coorte que alcançaram cada estado"
        physicalAxis={form === "column"}
      />
    ),
    [funnelRows, funnel.cohort, tokens],
  );

  /* --------------------------------------------------------- signals --- */
  const signals = data.signals;
  const tones = useMemo(
    () => signalTones(signals.types, tokens),
    [signals.types, tokens],
  );
  const signalSeries = useMemo(() => {
    const dayIndex = new Map(signals.days.map((day, index) => [day, index]));
    return signals.types.map((type) => {
      const values = signals.days.map(() => 0);
      for (const cell of signals.cells) {
        if (cell.signal_type !== type.signal_type) continue;
        const index = dayIndex.get(cell.day);
        if (index !== undefined) values[index] = cell.count;
      }
      return {
        key: type.signal_type,
        label: `${signalLabels[type.signal_type] ?? type.signal_type} (sev. ${type.severity})`,
        color: tones[type.signal_type] ?? tokens.aco,
        values,
        total: type.total,
      };
    });
  }, [signals, tones, tokens]);
  const signalChart = useCallback(
    (form: ChartForm) => (
      <AresChart
        formKey={form}
        option={stackedOption(
          form,
          {
            categories: signals.days.map(shortDay),
            series: signalSeries,
            measure: "sinais",
            format: count,
            stack: "signals",
          },
          tokens,
        )}
        label="Sinais detectados por dia, empilhados por tipo"
      />
    ),
    [signals.days, signalSeries, tokens],
  );

  /* --------------------------------------------------------- heatmap --- */
  const heatmap = data.heatmap;
  const heatCells = useMemo(
    () =>
      heatmap.cells.map(
        (cell) =>
          [cell.weekday, 3 - cell.band, cell.count] as [number, number, number],
      ),
    [heatmap],
  );
  const heatChart = useCallback(
    (form: ChartForm) => (
      <AresChart
        formKey={form}
        option={heatmapOption(
          form,
          {
            columns: WEEKDAYS,
            rows: HOUR_BANDS,
            cells: heatCells,
            measure: "sinais",
            base: tokens.aco,
          },
          tokens,
        )}
        label="Sinais detectados por dia da semana e faixa horária (UTC)"
      />
    ),
    [heatCells, tokens],
  );

  return (
    <section
      className="cc-analysis-grid"
      aria-label="Análises do Command Center"
    >
      <ChartFrame
        {...metadata}
        className="chart-trend"
        title="Fluxo de atenção"
        definition="Quantas oportunidades abriram, foram trabalhadas, tiveram ação executada ou falharam, por dia"
        unit="Contagem por dia · UTC"
        state={frameState(true, !trendHasData)}
        partialMessage={`O primeiro dia da janela pode estar incompleto (a janela começa no mesmo horário, ${days} dias atrás).`}
        hasData={trendHasData}
        emptyMessage="Nenhuma abertura, intervenção ou execução no período. Amplie o período ou verifique as conexões."
        forms={TREND_FORMS}
        formKey="cc-trend"
        renderForm={trendChart}
        table={
          <table className="chart-data-table">
            <caption className="sr-only">Fluxo de atenção por dia</caption>
            <thead>
              <tr>
                <th scope="col">Dia</th>
                {trends.series.map((entry) => (
                  <th scope="col" key={entry.key}>
                    {entry.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trends.days.map((day, index) => (
                <tr key={day}>
                  <th scope="row">{shortDay(day)}</th>
                  {trends.series.map((entry) => (
                    <td key={entry.key}>{entry.values[index] ?? 0}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        }
      />
      <ChartFrame
        {...metadata}
        className="chart-funnel"
        title="Funil de intervenção"
        definition="De cada oportunidade aberta no período, até que estado o ARES a levou"
        unit="Oportunidades da coorte"
        attribution="Observação; causalidade não demonstrada"
        state={frameState(true, funnel.cohort === 0)}
        partialMessage={`Coorte de ${funnel.cohort} abertas no período. Como qualquer estado pode ir direto para Encerradas, uma etapa posterior pode superar a anterior.${missingDetected > 0 ? ` ${missingDetected} sem transição detected registrada.` : ""}`}
        hasData={funnel.cohort > 0}
        emptyMessage="Nenhuma oportunidade aberta no período; o funil só conta oportunidades que entraram nesta janela."
        forms={FUNNEL_FORMS}
        formKey="cc-funnel"
        renderForm={funnelChart}
        table={
          <ChartDataTable
            title="Funil de intervenção"
            rows={funnelRows}
            unit="Oportunidades"
          />
        }
      />
      <ChartFrame
        {...metadata}
        className="chart-signals"
        title="Sinais por tipo"
        definition="Quantos sinais o ARES detectou por dia e de que tipo"
        unit="Sinais detectados por dia · UTC"
        state={frameState(signals.without_opportunity > 0, signals.total === 0)}
        partialMessage={`${signals.without_opportunity} sinal(is) sem oportunidade vinculada fora da leitura por escopo.`}
        hasData={signals.total > 0}
        emptyMessage="Nenhum sinal detectado no período. Sinais surgem quando eventos do CRM chegam ao pipeline."
        forms={SIGNAL_FORMS}
        formKey="cc-signals"
        renderForm={signalChart}
        table={
          <table className="chart-data-table">
            <caption className="sr-only">Sinais por tipo e por dia</caption>
            <thead>
              <tr>
                <th scope="col">Dia</th>
                {signalSeries.map((entry) => (
                  <th scope="col" key={entry.key}>
                    {entry.label}
                  </th>
                ))}
                <th scope="col">Total</th>
              </tr>
            </thead>
            <tbody>
              {signals.days.map((day, index) => (
                <tr key={day}>
                  <th scope="row">{shortDay(day)}</th>
                  {signalSeries.map((entry) => (
                    <td key={entry.key}>{entry.values[index]}</td>
                  ))}
                  <td>
                    {signalSeries.reduce(
                      (sum, entry) => sum + (entry.values[index] ?? 0),
                      0,
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        }
      >
        {signalSeries.length ? (
          <ChartLegend
            compact
            rows={signalSeries.map((entry) => ({
              id: entry.key,
              label: entry.label,
              value: entry.total,
              color: entry.color,
            }))}
          />
        ) : null}
      </ChartFrame>
      <ChartFrame
        {...metadata}
        className="chart-heat"
        title="Quando os sinais são detectados"
        definition="Em que dia e faixa de horário o ARES registra sinais — concentração de processamento, não comportamento do cliente"
        unit="Sinais · horário de detecção (UTC)"
        state={frameState(false, heatmap.total === 0)}
        hasData={heatmap.total > 0}
        emptyMessage="Nenhum sinal no período; a grade aparece quando o pipeline registra detecções."
        forms={HEAT_FORMS}
        formKey="cc-heat"
        renderForm={heatChart}
        table={
          <ChartDataTable
            title="Quando os sinais são detectados"
            rows={heatCells.map(([column, row, value]) => ({
              label: `${WEEKDAYS[column]} · ${HOUR_BANDS[row]}`,
              value,
            }))}
            unit="Sinais"
          />
        }
      />
    </section>
  );
}
