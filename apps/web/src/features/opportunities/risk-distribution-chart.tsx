import { useMemo } from "react";
import type { EChartsCoreOption } from "echarts/core";

import { AresChart } from "@/charts/AresChart";
import {
  ChartDataTable,
  ChartFrame,
  ChartLegend,
  type ChartMetadata,
} from "@/charts/ChartFrame";
import {
  aresTooltip,
  categoryAxis,
  raisedBar,
  raisedBarEmphasis,
  useThemeTokens,
  valueAxis,
} from "@/charts/aresTheme";

import type { OpportunityListItem } from "./types";

export function RiskDistributionChart({
  items,
  freshness,
  source,
  state = "ready",
  onRetry,
  partialMessage,
}: ChartMetadata & { items: OpportunityListItem[] }) {
  const tokens = useThemeTokens();
  const rows = useMemo(
    () => [
      {
        label: "Crítica",
        value: items.filter((item) => item.priority === 0).length,
        color: tokens.brasa,
        worsening: true,
      },
      {
        label: "Alta",
        value: items.filter((item) => item.priority === 1).length,
        color: tokens.ambar,
        worsening: true,
      },
      {
        label: "Média",
        value: items.filter((item) => item.priority === 2).length,
        color: tokens.aco,
      },
      {
        label: "Baixa",
        value: items.filter((item) => item.priority === 3).length,
        color: tokens.jade,
      },
    ],
    [items, tokens],
  );
  const unclassified = items.filter(
    (item) => ![0, 1, 2, 3].includes(item.priority),
  ).length;
  const option = useMemo<EChartsCoreOption>(
    () => ({
      textStyle: { fontFamily: tokens.font, color: tokens.ink },
      grid: { left: 34, right: 10, top: 26, bottom: 27 },
      tooltip: { ...aresTooltip(tokens), trigger: "axis" },
      xAxis: categoryAxis(
        tokens,
        rows.map((item) => item.label),
      ),
      yAxis: valueAxis(tokens),
      series: [
        {
          id: "priority-count",
          name: "Oportunidades",
          type: "bar",
          barMaxWidth: 36,
          label: {
            show: true,
            position: "top",
            color: tokens.ink,
            fontSize: 12,
            fontWeight: 650,
          },
          data: rows.map((item) => ({
            name: item.label,
            value: item.value,
            itemStyle: raisedBar(item.color, tokens),
          })),
          emphasis: raisedBarEmphasis(tokens),
        },
      ],
    }),
    [rows, tokens],
  );

  return (
    <ChartFrame
      title="Pressão por prioridade"
      definition="Distribuição da fila conforme a classificação do ARES"
      unit="Oportunidades"
      period="Fila no recorte atual"
      freshness={freshness}
      source={source}
      state={
        state === "ready"
          ? items.length === 0
            ? "empty"
            : unclassified
              ? "partial"
              : "ready"
          : state
      }
      onRetry={onRetry}
      hasData={items.length > 0}
      partialMessage={
        unclassified
          ? `${unclassified} registro(s) sem classificação válida ficam fora das barras.`
          : partialMessage
      }
      table={
        <ChartDataTable
          title="Pressão por prioridade"
          rows={[
            ...rows,
            ...(unclassified
              ? [
                  {
                    label: "Sem classificação",
                    value: unclassified,
                    color: tokens.aco,
                  },
                ]
              : []),
          ]}
          unit="Oportunidades"
        />
      }
    >
      <AresChart
        option={option}
        label="Contagem de oportunidades críticas, altas, médias e baixas"
        physicalAxis
      />
      <ChartLegend rows={rows} compact />
    </ChartFrame>
  );
}
