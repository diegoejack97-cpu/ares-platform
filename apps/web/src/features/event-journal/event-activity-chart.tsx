import { useEffect, useMemo, useRef } from "react";
import { LineChart } from "echarts/charts";
import {
  DatasetComponent,
  GridComponent,
  TooltipComponent,
} from "echarts/components";
import { init, use as registerEChartsComponents } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

import type { JournalEvent } from "./types";

registerEChartsComponents([
  LineChart,
  DatasetComponent,
  GridComponent,
  TooltipComponent,
  CanvasRenderer,
]);

type EventActivityChartProps = {
  events: JournalEvent[];
};

export function EventActivityChart({ events }: EventActivityChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const series = useMemo(
    () =>
      [...events].reverse().map((event, index) => [
        new Intl.DateTimeFormat("pt-BR", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }).format(new Date(event.recorded_at)),
        index + 1,
      ]),
    [events],
  );

  useEffect(() => {
    if (!chartRef.current || series.length === 0) return;

    const chart = init(chartRef.current, undefined, { renderer: "canvas" });
    chart.setOption({
      animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      dataset: { source: [["Horário", "Eventos acumulados"], ...series] },
      grid: { left: 44, right: 16, top: 16, bottom: 28 },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        axisLine: { lineStyle: { color: "#c9cec9" } },
        axisLabel: { color: "#65706c", fontSize: 11 },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { color: "#65706c", fontSize: 11 },
        splitLine: { lineStyle: { color: "#e4e6e1" } },
      },
      series: [
        {
          type: "line",
          encode: { x: "Horário", y: "Eventos acumulados" },
          showSymbol: true,
          symbolSize: 7,
          lineStyle: { color: "#2f6b59", width: 2 },
          itemStyle: {
            color: "#2f6b59",
            borderColor: "#f5f4ef",
            borderWidth: 2,
          },
          areaStyle: { color: "rgba(47, 107, 89, 0.10)" },
        },
      ],
    });

    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(chartRef.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [series]);

  if (series.length === 0) {
    return (
      <div className="chart-empty" role="status">
        A série começa quando o primeiro evento do FakeCRM for registrado.
      </div>
    );
  }

  return (
    <div
      ref={chartRef}
      className="event-chart"
      role="img"
      aria-label="Linha de eventos acumulados recebidos do FakeCRM nesta sessão"
    />
  );
}
