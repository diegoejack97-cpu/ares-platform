import { useMemo } from "react";
import type { EChartsCoreOption } from "echarts/core";

import { AresChart } from "@/charts/AresChart";
import {
  ChartDataTable,
  ChartFrame,
  type ChartMetadata,
} from "@/charts/ChartFrame";
import {
  areaFill,
  aresTooltip,
  useThemeTokens,
  valueAxis,
} from "@/charts/aresTheme";

import type { JournalEvent } from "./types";

const dateFormatter = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "medium",
});
const timeFormatter = new Intl.DateTimeFormat("pt-BR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function EventActivityChart({
  events,
  freshness,
  source = "Event Journal / FakeCRM",
  state = "ready",
  onRetry,
  partialMessage,
}: ChartMetadata & { events: JournalEvent[] }) {
  const tokens = useThemeTokens();
  const validEvents = useMemo(
    () =>
      events
        .filter((event) => Number.isFinite(Date.parse(event.recorded_at)))
        .sort((a, b) => Date.parse(a.recorded_at) - Date.parse(b.recorded_at)),
    [events],
  );
  const rows = useMemo(
    () =>
      validEvents.map((event, index) => ({
        label: dateFormatter.format(new Date(event.recorded_at)),
        value: index + 1,
        detail: event.event_type,
        id: event.id,
      })),
    [validEvents],
  );
  const missing = events.length - validEvents.length;
  const option = useMemo<EChartsCoreOption>(
    () => ({
      textStyle: { fontFamily: tokens.font, color: tokens.ink },
      grid: { left: 34, right: 10, top: 20, bottom: 27 },
      tooltip: {
        ...aresTooltip(tokens),
        trigger: "axis",
        axisPointer: {
          type: "cross",
          lineStyle: { color: tokens.ink2 },
          label: { backgroundColor: tokens.raisedHi, color: tokens.ink },
        },
      },
      xAxis: {
        type: "time",
        splitNumber: 3,
        axisLine: { lineStyle: { color: tokens.edgeDark, width: 2 } },
        axisTick: { show: false },
        axisLabel: {
          color: tokens.ink2,
          fontSize: 11,
          hideOverlap: true,
          formatter: (value: number) => timeFormatter.format(new Date(value)),
        },
      },
      yAxis: valueAxis(tokens),
      series: [
        {
          id: "journal-activity",
          type: "line",
          name: "Eventos acumulados no recorte",
          showSymbol: validEvents.length <= 40,
          symbol: "circle",
          symbolSize: 7,
          data: validEvents.map((event, index) => ({
            name: event.id,
            value: [Date.parse(event.recorded_at), index + 1],
          })),
          lineStyle: {
            color: tokens.jade,
            width: 2.5,
            shadowColor: tokens.edgeDark,
            shadowOffsetY: 2,
            shadowBlur: 0,
          },
          itemStyle: {
            color: tokens.jade,
            borderColor: tokens.edgeDark,
            borderWidth: 1.5,
            shadowColor: tokens.edgeDark,
            shadowOffsetY: 2,
            shadowBlur: 0,
          },
          areaStyle: { color: areaFill(tokens.jade) },
          emphasis: { scale: 1.4 },
        },
      ],
    }),
    [tokens, validEvents],
  );
  const period = validEvents.length
    ? `${dateFormatter.format(new Date(validEvents[0].recorded_at))} até ${dateFormatter.format(new Date(validEvents[validEvents.length - 1].recorded_at))}`
    : "Recorte atual do Journal";
  return (
    <ChartFrame
      title="Entrada acumulada"
      definition="Registros recebidos ao longo do recorte exibido"
      unit="Eventos registrados"
      period={period}
      freshness={freshness}
      source={source}
      state={
        state === "ready"
          ? events.length === 0
            ? "empty"
            : missing
              ? "partial"
              : "ready"
          : state
      }
      onRetry={onRetry}
      partialMessage={
        missing
          ? `${missing} evento(s) sem data válida não entram na série temporal.`
          : partialMessage
      }
      hasData={validEvents.length > 0}
      emptyMessage="A série começa quando o primeiro evento válido é registrado no Journal."
      attribution="Atividade operacional; não representa receita"
      className="chart-event"
      table={
        <ChartDataTable
          title="Entrada acumulada no recorte do Journal"
          rows={rows.map((row) => ({
            ...row,
            label: `${row.label} · ${row.id.slice(0, 8)}`,
          }))}
          unit="Eventos acumulados"
        />
      }
    >
      <AresChart
        option={option}
        label="Linha de eventos acumulados, ordenados pela data de registro, somente no recorte retornado"
        physicalAxis
      />
      <p className="chart-event-caption">
        {validEvents.length} registros no recorte. A linha acompanha entradas
        reais do Journal.
      </p>
    </ChartFrame>
  );
}
