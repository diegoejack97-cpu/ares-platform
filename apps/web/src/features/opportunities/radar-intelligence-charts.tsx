import { useMemo, useState } from "react";
import type { EChartsCoreOption } from "echarts/core";

import { AresChart } from "@/charts/AresChart";
import {
  ChartDataTable,
  ChartFrame,
  ChartLegend,
  type ChartDatum,
  type ChartMetadata,
} from "@/charts/ChartFrame";
import {
  aresTooltip,
  bevelFill,
  categoryAxis,
  categoryColor,
  raisedBar,
  useThemeTokens,
  valueAxis,
} from "@/charts/aresTheme";
import { LiveValue } from "@/components/live/live-value";
import { finiteNumber, safeSum } from "@/lib/numbers";

import { money, signalLabels } from "./format";
import type { OpportunityListItem } from "./types";

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
  const signalRows: ChartDatum[] = signals.map((row) => ({
    ...row,
    color: categoryColor(row.label, tokens),
  }));
  const stageRows: ChartDatum[] = stages.map((row) => ({
    ...row,
    color: categoryColor(row.label, tokens),
  }));

  const stageOption = useMemo<EChartsCoreOption>(
    () => ({
      textStyle: { fontFamily: tokens.font, color: tokens.ink },
      grid: { left: 34, right: 10, top: 22, bottom: 27 },
      tooltip: {
        ...aresTooltip(tokens),
        trigger: "axis",
        valueFormatter: (value: unknown) => {
          const parsed = finiteNumber(value);
          return parsed === null ? "Não informado" : money(parsed, currency);
        },
      },
      xAxis: {
        ...categoryAxis(
          tokens,
          stages.map((item) => item.label),
        ),
        axisLabel: {
          color: tokens.ink2,
          fontSize: 10,
          interval: 0,
          width: 70,
          overflow: "truncate",
          hideOverlap: true,
        },
      },
      yAxis: {
        ...valueAxis(tokens),
        axisLabel: {
          color: tokens.ink2,
          fontSize: 10,
          formatter: (value: number) =>
            new Intl.NumberFormat("pt-BR", {
              notation: "compact",
              maximumFractionDigits: 1,
            }).format(value),
        },
      },
      series: [
        {
          id: "stage-value",
          type: "bar",
          name: `Valor observado (${currency})`,
          barMaxWidth: 36,
          data: stages.map((item) => ({
            name: item.label,
            value: item.value,
            itemStyle: raisedBar(categoryColor(item.label, tokens), tokens),
          })),
          emphasis: { itemStyle: { shadowOffsetY: 4, shadowBlur: 0 } },
        },
      ],
    }),
    [stages, tokens, currency],
  );

  const signalOption = useMemo<EChartsCoreOption>(
    () => ({
      textStyle: { fontFamily: tokens.font, color: tokens.ink },
      tooltip: {
        ...aresTooltip(tokens),
        trigger: "item",
        valueFormatter: (value: unknown) =>
          `${finiteNumber(value) ?? 0} oportunidades`,
      },
      series: [
        {
          id: "signal-track",
          type: "pie",
          radius: ["57%", "81%"],
          center: ["50%", "50%"],
          silent: true,
          z: 1,
          label: { show: false },
          tooltip: { show: false },
          data: [
            {
              value: 1,
              itemStyle: {
                color: tokens.well,
                borderColor: tokens.edgeDark,
                borderWidth: 2,
              },
            },
          ],
          animation: false,
        },
        {
          id: "signal-distribution",
          type: "pie",
          radius: ["57%", "81%"],
          center: ["50%", "50%"],
          z: 2,
          padAngle: 1.6,
          label: { show: false },
          labelLine: { show: false },
          minAngle: 2,
          emphasis: {
            scaleSize: 4,
            itemStyle: { shadowOffsetY: 4, shadowBlur: 0 },
          },
          itemStyle: {
            borderColor: tokens.edgeDark,
            borderWidth: 1,
            shadowColor: tokens.edgeDark,
            shadowOffsetY: 2,
            shadowBlur: 0,
          },
          data: signals.map((row) => ({
            name: row.label,
            value: row.value,
            itemStyle: {
              color: bevelFill(categoryColor(row.label, tokens)),
            },
          })),
        },
      ],
    }),
    [signals, tokens],
  );

  const slaOption = useMemo<EChartsCoreOption>(
    () => ({
      textStyle: { fontFamily: tokens.font, color: tokens.ink },
      grid: { left: 99, right: 28, top: 8, bottom: 20 },
      tooltip: {
        ...aresTooltip(tokens),
        trigger: "axis",
        axisPointer: { type: "shadow" },
      },
      xAxis: {
        ...valueAxis(tokens),
        max: Math.max(items.length, 1),
        splitNumber: 3,
      },
      yAxis: {
        ...categoryAxis(
          tokens,
          sla.map((item) => item.label),
        ),
        inverse: true,
        axisLine: { show: false },
        axisLabel: {
          color: tokens.ink2,
          fontSize: 11,
          width: 91,
          overflow: "truncate",
        },
      },
      series: [
        {
          id: "sla-window",
          name: "Oportunidades",
          type: "bar",
          barWidth: 15,
          showBackground: true,
          backgroundStyle: {
            color: tokens.well,
            borderColor: tokens.edgeDark,
            borderWidth: 1,
            borderRadius: tokens.radius,
          },
          label: {
            show: true,
            position: "right",
            color: tokens.ink,
            fontSize: 11,
            fontWeight: 650,
          },
          data: sla.map((item) => ({
            name: item.label,
            value: item.value,
            itemStyle: {
              ...raisedBar(item.color, tokens),
              borderRadius: tokens.radius,
            },
          })),
          emphasis: { itemStyle: { shadowOffsetY: 3, shadowBlur: 0 } },
        },
      ],
    }),
    [sla, tokens, items.length],
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
        table={
          <ChartDataTable
            title="Exposição por etapa"
            rows={stageRows}
            unit={currency}
            format={(value) => money(value, currency)}
          />
        }
      >
        <AresChart
          option={stageOption}
          label={`Valor observado por etapa, em ${currency}`}
          physicalAxis
        />
        <ChartLegend
          rows={stageRows}
          format={(value) => money(value, currency)}
          compact
        />
      </ChartFrame>
      <ChartFrame
        {...metadata}
        className="chart-signals"
        title="Sinais dominantes"
        definition="O motivo principal de atenção em cada oportunidade"
        unit="Oportunidades"
        period="Fila no recorte atual"
        attribution="Sinal observado; sem causalidade"
        hasData={items.length > 0}
        table={
          <ChartDataTable
            title="Sinais dominantes"
            rows={signalRows}
            unit="Oportunidades"
          />
        }
      >
        <div className="chart-donut-layout">
          <div className="chart-donut-plot">
            <AresChart
              option={signalOption}
              label="Composição das oportunidades por sinal dominante"
            />
            <div className="chart-donut-center">
              <strong>
                <LiveValue value={items.length} />
              </strong>
              <span>oportunidades</span>
            </div>
          </div>
          <ChartLegend rows={signalRows} />
        </div>
      </ChartFrame>
      <ChartFrame
        {...metadata}
        className="chart-sla"
        title="Janela de SLA"
        definition="Prazos que exigem resposta e cobertura de atendimento"
        unit="Oportunidades"
        period="Agora / próximas 24 horas"
        hasData={items.length > 0}
        table={
          <ChartDataTable
            title="Janela de SLA"
            rows={sla}
            unit="Oportunidades"
          />
        }
      >
        <AresChart
          option={slaOption}
          label="Oportunidades com SLA vencido, próximas 24h, após 24h e sem prazo válido"
        />
        <ChartLegend rows={sla} compact />
      </ChartFrame>
    </section>
  );
}
