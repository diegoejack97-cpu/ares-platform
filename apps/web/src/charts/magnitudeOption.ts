import type { EChartsCoreOption } from "echarts/core";

import {
  aresTooltip,
  areaFill,
  categoryAxis,
  ordinalRamp,
  raisedBar,
  raisedBarEmphasis,
  valueAxis,
  type AresThemeTokens,
} from "./aresTheme";
import type { ChartForm } from "./chartForms";

export interface MagnitudeRow {
  label: string;
  value: number | null;
  detail?: string;
  /** Overrides the ramp when the colour carries reserved meaning, such as SLA state. */
  color?: string;
}

export interface MagnitudeSpec {
  rows: MagnitudeRow[];
  /** Name of the measure, used in tooltips. */
  measure: string;
  format: (value: number) => string;
  /**
   * Ordered categories (funnel stages, tiers) get a monotone one-hue ramp.
   * Nominal ones get a single hue, so bar length alone carries magnitude.
   */
  ordered?: boolean;
  /** Base hue for the ramp. Ignored where a row sets its own reserved colour. */
  base: string;
  /** Reading a tooltip should give business meaning, not just the number. */
  describe?: (row: MagnitudeRow) => string;
  /** Reference line — a target, median, or threshold the reader compares against. */
  marker?: { value: number; label: string };
}

function paint(spec: MagnitudeSpec, tokens: AresThemeTokens) {
  const ramp = spec.ordered
    ? ordinalRamp(spec.base, spec.rows.length, tokens)
    : spec.rows.map(() => spec.base);
  return spec.rows.map((row, index) => row.color ?? ramp[index]);
}

function tooltip(spec: MagnitudeSpec, tokens: AresThemeTokens) {
  return {
    ...aresTooltip(tokens),
    trigger: "item" as const,
    formatter: (params: { name?: string; value?: unknown }) => {
      const row = spec.rows.find((entry) => entry.label === params.name);
      if (!row) return "";
      const amount =
        row.value === null ? "Não informado" : spec.format(row.value);
      const meaning = spec.describe?.(row);
      return [
        `<strong>${row.label}</strong>`,
        `${spec.measure}: ${amount}`,
        meaning ?? "",
        row.detail ?? "",
      ]
        .filter(Boolean)
        .join("<br/>");
    },
  };
}

function markLine(spec: MagnitudeSpec, tokens: AresThemeTokens, axis: "x" | "y") {
  if (!spec.marker) return undefined;
  return {
    silent: true,
    symbol: "none" as const,
    label: {
      formatter: spec.marker.label,
      color: tokens.ink2,
      fontSize: 10,
      position: axis === "y" ? ("insideEndTop" as const) : ("insideEndTop" as const),
    },
    lineStyle: { color: tokens.ink3, width: 1, type: "solid" as const },
    data: [axis === "y" ? { yAxis: spec.marker.value } : { xAxis: spec.marker.value }],
  };
}

/**
 * One data shape, many honest forms. Every form here answers the same question —
 * how much, per category — so switching between them cannot change the claim.
 */
export function magnitudeOption(
  form: ChartForm,
  spec: MagnitudeSpec,
  tokens: AresThemeTokens,
): EChartsCoreOption {
  const colors = paint(spec, tokens);
  const labels = spec.rows.map((row) => row.label);
  const values = spec.rows.map((row) => row.value);
  const base = {
    textStyle: { fontFamily: tokens.font, color: tokens.ink },
    tooltip: tooltip(spec, tokens),
  };

  if (form === "column" || form === "bar") {
    const vertical = form === "column";
    const measureAxis = {
      ...valueAxis(tokens),
      axisLabel: {
        color: tokens.ink2,
        fontSize: 10,
        fontFamily: tokens.font,
        formatter: (value: number) => spec.format(value),
      },
    };
    const nameAxis = {
      ...categoryAxis(tokens, labels),
      ...(vertical
        ? {
            axisLabel: {
              color: tokens.ink2,
              fontSize: 10,
              interval: 0,
              width: 70,
              overflow: "truncate" as const,
              hideOverlap: true,
            },
          }
        : {
            inverse: true,
            axisLine: { show: false },
            axisLabel: {
              color: tokens.ink2,
              fontSize: 11,
              width: 122,
              overflow: "break" as const,
              lineHeight: 14,
            },
          }),
    };
    return {
      ...base,
      grid: vertical
        ? { left: 52, right: 14, top: 22, bottom: 27 }
        : { left: 132, right: 34, top: 12, bottom: 26 },
      xAxis: vertical ? nameAxis : measureAxis,
      yAxis: vertical ? measureAxis : nameAxis,
      series: [
        {
          id: "magnitude",
          type: "bar",
          name: spec.measure,
          barMaxWidth: vertical ? 36 : 20,
          data: spec.rows.map((row, index) => ({
            name: row.label,
            value: row.value,
            itemStyle: {
              ...raisedBar(colors[index], tokens),
              borderRadius: vertical
                ? [tokens.radius, tokens.radius, 0, 0]
                : [0, tokens.radius, tokens.radius, 0],
            },
          })),
          label: vertical
            ? { show: false }
            : {
                show: true,
                position: "right" as const,
                color: tokens.ink,
                fontSize: 11,
                fontWeight: 650,
                formatter: ({ value }: { value: number | null }) =>
                  value === null ? "—" : spec.format(value),
              },
          markLine: markLine(spec, tokens, vertical ? "y" : "x"),
          emphasis: raisedBarEmphasis(tokens),
        },
      ],
    };
  }

  if (form === "funnel") {
    // Conversion between neighbours is the point of a funnel; the steepest fall
    // is named outright so the reader is not left counting percentages.
    const steps = spec.rows.map((row, index) => {
      const previous = index > 0 ? spec.rows[index - 1].value : null;
      const conversion =
        index > 0 && previous && previous > 0 && row.value !== null
          ? row.value / previous
          : null;
      return { row, conversion };
    });
    const worst = steps.reduce<{ index: number; value: number } | null>(
      (lowest, step, index) =>
        step.conversion !== null &&
        (lowest === null || step.conversion < lowest.value)
          ? { index, value: step.conversion }
          : lowest,
      null,
    );
    return {
      ...base,
      tooltip: {
        ...tooltip(spec, tokens),
        formatter: (params: { name?: string }) => {
          const position = spec.rows.findIndex(
            (entry) => entry.label === params.name,
          );
          const step = steps[position];
          if (!step) return "";
          const amount =
            step.row.value === null ? "Não informado" : spec.format(step.row.value);
          const drop =
            step.conversion === null
              ? "Primeira etapa do recorte."
              : `${(step.conversion * 100).toFixed(0)}% do que entrou na etapa anterior` +
                (worst?.index === position ? " — a maior queda do funil." : ".");
          return `<strong>${step.row.label}</strong><br/>${spec.measure}: ${amount}<br/>${drop}`;
        },
      },
      series: [
        {
          id: "magnitude",
          type: "funnel",
          name: spec.measure,
          top: 14,
          bottom: 14,
          left: "8%",
          right: "8%",
          minSize: "22%",
          sort: "none",
          gap: 2,
          // The conversion is on the band itself: a tooltip must never be the only
          // way to read a value.
          label: {
            show: true,
            position: "inside",
            color: tokens.ink,
            fontSize: 11,
            fontWeight: 650,
            formatter: ({ name }: { name: string }) => {
              const position = spec.rows.findIndex((row) => row.label === name);
              const step = steps[position];
              if (!step || step.conversion === null) return name;
              const pace = `${(step.conversion * 100).toFixed(0)}%`;
              return worst?.index === position
                ? `${name}  ▼ ${pace}`
                : `${name}  ${pace}`;
            },
          },
          labelLine: { show: false },
          data: steps.map((step, index) => ({
            name: step.row.label,
            value: step.row.value ?? 0,
            itemStyle: {
              color: colors[index],
              borderColor: tokens.edgeDark,
              borderWidth: 1,
            },
          })),
          emphasis: { label: { fontSize: 12 } },
        },
      ],
    };
  }

  if (form === "treemap") {
    return {
      ...base,
      series: [
        {
          id: "magnitude",
          type: "treemap",
          name: spec.measure,
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          top: 6,
          bottom: 6,
          left: 6,
          right: 6,
          itemStyle: { borderColor: tokens.edgeDark, borderWidth: 2, gapWidth: 2 },
          label: {
            show: true,
            color: tokens.ink,
            fontSize: 11,
            fontWeight: 600,
            overflow: "truncate",
          },
          data: spec.rows.map((row, index) => ({
            name: row.label,
            value: row.value ?? 0,
            itemStyle: { color: colors[index] },
          })),
        },
      ],
    };
  }

  if (form === "donut") {
    return {
      ...base,
      series: [
        {
          id: "magnitude",
          type: "pie",
          name: spec.measure,
          radius: ["52%", "78%"],
          center: ["50%", "52%"],
          padAngle: 2,
          itemStyle: { borderColor: tokens.edgeDark, borderWidth: 1 },
          label: { show: false },
          data: spec.rows.map((row, index) => ({
            name: row.label,
            value: row.value ?? 0,
            itemStyle: { color: colors[index] },
          })),
        },
      ],
    };
  }

  // line / area: only offered where the categories carry an order worth tracing.
  return {
    ...base,
    grid: { left: 52, right: 14, top: 22, bottom: 27 },
    xAxis: categoryAxis(tokens, labels),
    yAxis: {
      ...valueAxis(tokens),
      axisLabel: {
        color: tokens.ink2,
        fontSize: 10,
        fontFamily: tokens.font,
        formatter: (value: number) => spec.format(value),
      },
    },
    series: [
      {
        id: "magnitude",
        type: "line",
        name: spec.measure,
        data: values,
        smooth: false,
        symbolSize: 8,
        lineStyle: {
          color: spec.base,
          width: 2,
          shadowColor: tokens.edgeDark,
          shadowOffsetY: tokens.lift,
          shadowBlur: 0,
        },
        itemStyle: {
          color: spec.base,
          borderColor: tokens.edgeDark,
          borderWidth: 1.5,
        },
        areaStyle: form === "area" ? { color: areaFill(spec.base) } : undefined,
        markLine: markLine(spec, tokens, "y"),
      },
    ],
  };
}
