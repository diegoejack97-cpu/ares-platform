import type { EChartsCoreOption } from "echarts/core";

import {
  areaFill,
  aresTooltip,
  categoryAxis,
  raisedBar,
  shade,
  tint,
  valueAxis,
  type AresThemeTokens,
} from "./aresTheme";
import type { ChartForm } from "./chartForms";

/* ---------------------------------------------------------------- trend --- */

export interface TrendSeries {
  key: string;
  label: string;
  color: string;
  /** Dash pattern, so series stay separable without relying on colour alone. */
  dash?: number[];
  points: Array<[number, number]>;
}

export interface TrendSpec {
  series: TrendSeries[];
  measure: string;
  format: (value: number) => string;
}

/**
 * Change over time. A crosshair reads every series at one instant, which is the
 * question a trend actually answers — not the value of one isolated point.
 */
export function trendOption(
  form: ChartForm,
  spec: TrendSpec,
  tokens: AresThemeTokens,
): EChartsCoreOption {
  const single = spec.series.length === 1;
  return {
    textStyle: { fontFamily: tokens.font, color: tokens.ink },
    grid: { left: 46, right: 16, top: single ? 16 : 30, bottom: 26 },
    legend: single
      ? { show: false }
      : {
          show: true,
          top: 0,
          right: 0,
          itemWidth: 14,
          itemHeight: 2,
          textStyle: { color: tokens.ink2, fontSize: 10, fontFamily: tokens.font },
          data: spec.series.map((entry) => entry.label),
        },
    tooltip: {
      ...aresTooltip(tokens),
      trigger: "axis",
      axisPointer: {
        type: "line",
        lineStyle: { color: tokens.ink3, width: 1, type: "solid" },
      },
      valueFormatter: (value: unknown) =>
        typeof value === "number" ? spec.format(value) : "Não informado",
    },
    xAxis: {
      type: "time",
      axisLine: { lineStyle: { color: tokens.edge, width: 1 } },
      axisTick: { show: false },
      axisLabel: {
        color: tokens.ink2,
        fontSize: 10,
        fontFamily: tokens.font,
        hideOverlap: true,
      },
    },
    yAxis: {
      ...valueAxis(tokens),
      axisLabel: {
        color: tokens.ink2,
        fontSize: 10,
        fontFamily: tokens.font,
        formatter: (value: number) => spec.format(value),
      },
    },
    series: spec.series.map((entry) => ({
      id: entry.key,
      name: entry.label,
      type: "line",
      data: entry.points,
      // A sparse series must show its observations: joining four points with a
      // bare line reads as a trend the data does not support.
      showSymbol: entry.points.length <= 12,
      symbolSize: 8,
      smooth: false,
      lineStyle: {
        color: entry.color,
        width: 2,
        type: entry.dash ?? "solid",
        shadowColor: tokens.edgeDark,
        shadowOffsetY: tokens.lift,
        shadowBlur: 0,
      },
      itemStyle: {
        color: entry.color,
        borderColor: tokens.edgeDark,
        borderWidth: 1.5,
      },
      areaStyle:
        form === "area" && single ? { color: areaFill(entry.color) } : undefined,
    })),
  };
}

/* -------------------------------------------------------------- heatmap --- */

export interface HeatmapSpec {
  /** Column labels, e.g. weekdays. */
  columns: string[];
  /** Row labels, e.g. hour bands, top to bottom. */
  rows: string[];
  /** [columnIndex, rowIndex, value] */
  cells: Array<[number, number, number]>;
  measure: string;
  base: string;
}

/**
 * Concentration across two dimensions. Magnitude here is sequential: one hue,
 * light to dark, so no cell claims an identity it does not have.
 */
export function heatmapOption(
  form: ChartForm,
  spec: HeatmapSpec,
  tokens: AresThemeTokens,
): EChartsCoreOption {
  const max = spec.cells.reduce((peak, cell) => Math.max(peak, cell[2]), 0);

  if (form === "column" || form === "bar") {
    // Collapsed to one dimension when the reader wants a plain ranking.
    const totals = spec.columns.map((label, index) => ({
      label,
      value: spec.cells
        .filter((cell) => cell[0] === index)
        .reduce((sum, cell) => sum + cell[2], 0),
    }));
    return {
      textStyle: { fontFamily: tokens.font, color: tokens.ink },
      grid: { left: 46, right: 16, top: 18, bottom: 26 },
      tooltip: { ...aresTooltip(tokens), trigger: "axis" },
      xAxis: categoryAxis(
        tokens,
        totals.map((row) => row.label),
      ),
      yAxis: valueAxis(tokens),
      series: [
        {
          id: "heat-total",
          type: "bar",
          name: spec.measure,
          barMaxWidth: 30,
          data: totals.map((row) => ({
            name: row.label,
            value: row.value,
            itemStyle: raisedBar(spec.base, tokens),
          })),
        },
      ],
    };
  }

  return {
    textStyle: { fontFamily: tokens.font, color: tokens.ink },
    grid: { left: 62, right: 14, top: 10, bottom: 44 },
    tooltip: {
      ...aresTooltip(tokens),
      trigger: "item",
      formatter: (params: { value?: unknown }) => {
        const cell = params.value as [number, number, number];
        return `<strong>${spec.columns[cell[0]]}, ${spec.rows[cell[1]]}</strong><br/>${cell[2]} ${spec.measure}`;
      },
    },
    xAxis: {
      type: "category",
      data: spec.columns,
      splitArea: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: tokens.ink2, fontSize: 10, fontFamily: tokens.font },
    },
    yAxis: {
      type: "category",
      data: spec.rows,
      splitArea: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: tokens.ink2, fontSize: 10, fontFamily: tokens.font },
    },
    visualMap: {
      min: 0,
      max: Math.max(max, 1),
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 10,
      itemHeight: 90,
      text: [`${max}`, "0"],
      textStyle: { color: tokens.ink3, fontSize: 10, fontFamily: tokens.font },
      inRange: { color: [tokens.well, tint(spec.base, 0.1), shade(spec.base, 0.3)] },
    },
    series: [
      {
        id: "heat",
        type: "heatmap",
        name: spec.measure,
        data: spec.cells,
        itemStyle: { borderColor: tokens.edgeDark, borderWidth: 1, borderRadius: 2 },
        emphasis: { itemStyle: { borderColor: tokens.ink, borderWidth: 1.5 } },
        progressive: 0,
      },
    ],
  };
}

/* --------------------------------------------------------------- matrix --- */

export interface MatrixPoint {
  id: string;
  label: string;
  x: number;
  y: number;
  color: string;
  detail?: string;
}

export interface MatrixSpec {
  points: MatrixPoint[];
  xName: string;
  yName: string;
  formatX: (value: number) => string;
  formatY: (value: number) => string;
  /** Splits the plane into quadrants the reader can name. */
  divider?: { x: number; y: number; quadrant: string };
}

/**
 * Two measures at once, so concentration and outliers become visible. Marks are
 * capped at three colours because any two points can sit side by side here.
 */
export function matrixOption(
  form: ChartForm,
  spec: MatrixSpec,
  tokens: AresThemeTokens,
): EChartsCoreOption {
  return {
    textStyle: { fontFamily: tokens.font, color: tokens.ink },
    grid: { left: 58, right: 18, top: 18, bottom: 34 },
    tooltip: {
      ...aresTooltip(tokens),
      trigger: "item",
      formatter: (params: { data?: unknown }) => {
        const point = (params.data as { point?: MatrixPoint })?.point;
        if (!point) return "";
        return [
          `<strong>${point.label}</strong>`,
          `${spec.xName}: ${spec.formatX(point.x)}`,
          `${spec.yName}: ${spec.formatY(point.y)}`,
          point.detail ?? "",
        ]
          .filter(Boolean)
          .join("<br/>");
      },
    },
    xAxis: {
      ...valueAxis(tokens),
      name: spec.xName,
      nameLocation: "middle",
      nameGap: 22,
      nameTextStyle: { color: tokens.ink3, fontSize: 10, fontFamily: tokens.font },
      axisLabel: {
        color: tokens.ink2,
        fontSize: 10,
        fontFamily: tokens.font,
        formatter: (value: number) => spec.formatX(value),
      },
    },
    yAxis: {
      ...valueAxis(tokens),
      name: spec.yName,
      nameLocation: "middle",
      nameGap: 44,
      nameTextStyle: { color: tokens.ink3, fontSize: 10, fontFamily: tokens.font },
      axisLabel: {
        color: tokens.ink2,
        fontSize: 10,
        fontFamily: tokens.font,
        formatter: (value: number) => spec.formatY(value),
      },
    },
    series: [
      {
        id: "matrix",
        type: form === "heatmap" ? "effectScatter" : "scatter",
        name: `${spec.yName} por ${spec.xName}`,
        symbolSize: 11,
        data: spec.points.map((point) => ({
          value: [point.x, point.y],
          point,
          itemStyle: {
            color: point.color,
            borderColor: tokens.edgeDark,
            borderWidth: 1.5,
            shadowColor: tokens.edgeDark,
            shadowOffsetY: tokens.lift,
            shadowBlur: 0,
          },
        })),
        markLine: spec.divider
          ? {
              silent: true,
              symbol: "none",
              label: { show: false },
              lineStyle: { color: tokens.edgeHi, width: 1, type: "solid" },
              data: [{ xAxis: spec.divider.x }, { yAxis: spec.divider.y }],
            }
          : undefined,
        markArea: spec.divider
          ? {
              silent: true,
              itemStyle: { color: "transparent" },
              label: {
                show: true,
                position: "insideTopRight",
                color: tokens.ink3,
                fontSize: 10,
                fontFamily: tokens.font,
                formatter: spec.divider.quadrant,
              },
              data: [
                [
                  { xAxis: spec.divider.x, yAxis: spec.divider.y },
                  { xAxis: "max", yAxis: "max" },
                ],
              ],
            }
          : undefined,
      },
    ],
  };
}
