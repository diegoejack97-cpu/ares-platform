import { useEffect, useMemo, useRef, useState } from "react";
import { BarChart, PieChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import {
  init,
  use as registerECharts,
  type EChartsCoreOption,
} from "echarts/core";
import { SVGRenderer } from "echarts/renderers";

import { money, signalLabels } from "./format";
import type { OpportunityListItem } from "./types";

registerECharts([
  BarChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  SVGRenderer,
]);

interface ChartDatum {
  label: string;
  value: number;
  formatted?: string;
}

function useThemeRevision() {
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const observer = new MutationObserver(() =>
      setRevision((current) => current + 1),
    );
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class", "data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  return revision;
}

function chartTokens() {
  const styles = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) =>
    styles.getPropertyValue(name).trim() || fallback;
  return {
    text: token("--foreground", "#18272b"),
    muted: token("--muted-foreground", "#66736f"),
    line: token("--border", "#d5d8d1"),
    surface: token("--card", "#fbfaf6"),
    primary: token("--chart-1", "#2f6b59"),
    amber: token("--chart-2", "#c78b39"),
    blue: token("--chart-3", "#497789"),
    red: token("--chart-4", "#9b5a4f"),
    gray: token("--chart-5", "#68706a"),
  };
}

function ChartFrame({
  label,
  option,
}: {
  label: string;
  option: EChartsCoreOption;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const tokens = chartTokens();
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const chart = init(ref.current, undefined, { renderer: "svg" });
    chart.setOption({
      animation: !reducedMotion,
      animationDuration: 650,
      animationDurationUpdate: 420,
      animationEasing: "cubicOut",
      animationEasingUpdate: "cubicOut",
      backgroundColor: "transparent",
      textStyle: { color: tokens.text, fontFamily: "Geist Variable" },
      ...option,
    });
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(ref.current);
    return () => {
      resizeObserver.disconnect();
      chart.dispose();
    };
  }, [option]);

  return (
    <div
      ref={ref}
      className="intelligence-chart"
      role="img"
      aria-label={label}
    />
  );
}

function AccessibleData({
  label,
  data,
}: {
  label: string;
  data: ChartDatum[];
}) {
  return (
    <details className="chart-data-alternative">
      <summary>Ver dados</summary>
      <table>
        <caption className="sr-only">{label}</caption>
        <thead>
          <tr>
            <th>Categoria</th>
            <th>Valor</th>
          </tr>
        </thead>
        <tbody>
          {data.map((item) => (
            <tr key={item.label}>
              <td>{item.label}</td>
              <td className="tabular">{item.formatted ?? item.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function groupBy<T>(
  items: T[],
  keyOf: (item: T) => string,
  valueOf: (item: T) => number,
) {
  const values = new Map<string, number>();
  for (const item of items) {
    const key = keyOf(item);
    values.set(key, (values.get(key) ?? 0) + valueOf(item));
  }
  return [...values.entries()].map(([label, value]) => ({ label, value }));
}

export function RadarIntelligenceCharts({
  items,
  now,
}: {
  items: OpportunityListItem[];
  now: number;
}) {
  const themeRevision = useThemeRevision();
  const tokens = useMemo(
    () => ({ ...chartTokens(), revision: themeRevision }),
    [themeRevision],
  );
  const stages = useMemo(
    () =>
      groupBy(
        items,
        (item) => item.external_stage ?? "Sem estágio",
        (item) => item.deal_value,
      )
        .sort((a, b) => b.value - a.value)
        .slice(0, 6),
    [items],
  );
  const signals = useMemo(
    () =>
      groupBy(
        items,
        (item) =>
          signalLabels[item.primary_signal_type ?? ""] ??
          item.primary_signal_type ??
          "Sem sinal",
        () => 1,
      )
        .sort((a, b) => b.value - a.value)
        .slice(0, 5),
    [items],
  );
  const sla = useMemo(() => {
    const nextDay = now + 86_400_000;
    const data = [
      { label: "Vencido", value: 0 },
      { label: "Próximas 24h", value: 0 },
      { label: "Depois de 24h", value: 0 },
      { label: "Sem SLA", value: 0 },
    ];
    for (const item of items) {
      if (!item.sla_at) data[3].value += 1;
      else if (new Date(item.sla_at).getTime() < now) data[0].value += 1;
      else if (new Date(item.sla_at).getTime() <= nextDay) data[1].value += 1;
      else data[2].value += 1;
    }
    return data;
  }, [items, now]);

  const stageOption = useMemo<EChartsCoreOption>(
    () => ({
      grid: { left: 8, right: 18, top: 16, bottom: 32, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: tokens.surface,
        borderColor: tokens.line,
        textStyle: { color: tokens.text },
        valueFormatter: (value: unknown) => money(Number(value)),
      },
      xAxis: {
        type: "category",
        data: stages.map((item) => item.label),
        axisLabel: {
          color: tokens.muted,
          interval: 0,
          rotate: stages.length > 4 ? 18 : 0,
        },
        axisLine: { lineStyle: { color: tokens.line } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: tokens.muted,
          formatter: (value: number) => `${Math.round(value / 1000)}k`,
        },
        splitLine: { lineStyle: { color: tokens.line, type: "dashed" } },
      },
      series: [
        {
          type: "bar",
          data: stages.map((item) => item.value),
          barMaxWidth: 34,
          itemStyle: { color: tokens.primary, borderRadius: [2, 2, 0, 0] },
        },
      ],
    }),
    [stages, tokens],
  );
  const signalOption = useMemo<EChartsCoreOption>(
    () => ({
      color: [
        tokens.red,
        tokens.amber,
        tokens.blue,
        tokens.primary,
        tokens.gray,
      ],
      tooltip: {
        trigger: "item",
        backgroundColor: tokens.surface,
        borderColor: tokens.line,
        textStyle: { color: tokens.text },
      },
      legend: {
        bottom: 0,
        left: "center",
        textStyle: { color: tokens.muted, fontSize: 10 },
        itemWidth: 9,
        itemHeight: 9,
      },
      series: [
        {
          type: "pie",
          radius: ["45%", "70%"],
          center: ["50%", "43%"],
          avoidLabelOverlap: true,
          label: { show: false },
          emphasis: { scaleSize: 5 },
          data: signals.map((item) => ({
            name: item.label,
            value: item.value,
          })),
        },
      ],
    }),
    [signals, tokens],
  );
  const slaOption = useMemo<EChartsCoreOption>(
    () => ({
      color: [tokens.red, tokens.amber, tokens.blue, tokens.gray],
      grid: { left: 14, right: 14, top: 42, bottom: 26 },
      tooltip: {
        trigger: "axis",
        backgroundColor: tokens.surface,
        borderColor: tokens.line,
        textStyle: { color: tokens.text },
      },
      legend: {
        top: 4,
        textStyle: { color: tokens.muted, fontSize: 10 },
        itemWidth: 10,
        itemHeight: 10,
      },
      xAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { color: tokens.muted },
        splitLine: { lineStyle: { color: tokens.line, type: "dashed" } },
      },
      yAxis: {
        type: "category",
        data: ["Fila atual"],
        axisLabel: { color: tokens.muted },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: sla.map((item) => ({
        name: item.label,
        type: "bar",
        stack: "sla",
        data: [item.value],
        barWidth: 28,
      })),
    }),
    [sla, tokens],
  );

  const stageData = stages.map((item) => ({
    ...item,
    formatted: money(item.value),
  }));

  return (
    <section className="radar-intelligence-grid" aria-label="Análises do Radar">
      <article className="panel intelligence-panel intelligence-panel-wide">
        <div className="panel-heading">
          <div>
            <span className="analysis-kicker">EXPOSIÇÃO COMERCIAL</span>
            <h2>Valor observado por etapa</h2>
            <p>Onde o valor em risco está concentrado agora</p>
          </div>
        </div>
        <ChartFrame
          label="Valor observado por etapa do funil"
          option={stageOption}
        />
        <AccessibleData label="Valor observado por etapa" data={stageData} />
      </article>
      <article className="panel intelligence-panel">
        <div className="panel-heading">
          <div>
            <span className="analysis-kicker">CAUSA OPERACIONAL</span>
            <h2>Sinais dominantes</h2>
            <p>Composição atual, não causalidade</p>
          </div>
        </div>
        <ChartFrame
          label="Distribuição dos sinais dominantes"
          option={signalOption}
        />
        <AccessibleData label="Sinais dominantes" data={signals} />
      </article>
      <article className="panel intelligence-panel">
        <div className="panel-heading">
          <div>
            <span className="analysis-kicker">PRESSÃO DE TEMPO</span>
            <h2>Janela de SLA</h2>
            <p>Vencido, próximas 24h e demais prazos</p>
          </div>
        </div>
        <ChartFrame
          label="Distribuição das oportunidades por janela de SLA"
          option={slaOption}
        />
        <AccessibleData label="Janela de SLA" data={sla} />
      </article>
    </section>
  );
}
