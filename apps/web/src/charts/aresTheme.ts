import { useEffect, useState } from "react";
import { color, graphic, registerTheme } from "echarts/core";

/** Resolve CSS variables before giving colours to ECharts; SVG cannot resolve them. */
export function readThemeTokens() {
  const styles = getComputedStyle(document.documentElement);
  const token = (name: string) => styles.getPropertyValue(name).trim();
  return {
    font: token("--font"),
    ink: token("--ink"),
    ink2: token("--ink-2"),
    ink3: token("--ink-3"),
    well: token("--well"),
    panel: token("--panel"),
    raisedHi: token("--raised-hi"),
    edge: token("--edge"),
    edgeHi: token("--edge-hi"),
    edgeDark: token("--edge-dark"),
    grid: token("--grid"),
    brasa: token("--brasa"),
    ambar: token("--ambar"),
    jade: token("--jade"),
    aco: token("--aco"),
    lilas: token("--lilas"),
    radius: Number.parseFloat(token("--r-sm")) || 0,
  };
}

export type AresThemeTokens = ReturnType<typeof readThemeTokens>;

/** Category identity keeps its colour when a refetch changes the ordering. */
export function categoryColor(label: string, tokens: AresThemeTokens) {
  let hash = 0;
  for (const character of label)
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return [tokens.brasa, tokens.ambar, tokens.jade, tokens.aco, tokens.lilas][
    hash % 5
  ];
}

export function useThemeTokens() {
  const [tokens, setTokens] = useState(readThemeTokens);
  useEffect(() => {
    const observer = new MutationObserver(() => setTokens(readThemeTokens()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "class"],
    });
    return () => observer.disconnect();
  }, []);
  return tokens;
}

export function registerAresTheme(tokens: AresThemeTokens) {
  registerTheme("ares", {
    textStyle: { fontFamily: tokens.font, color: tokens.ink },
    categoryAxis: {
      axisLine: { lineStyle: { color: tokens.edgeDark, width: 2 } },
      axisTick: { show: false },
      axisLabel: { color: tokens.ink2, fontSize: 11 },
      splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: tokens.ink2, fontSize: 11 },
      splitLine: { lineStyle: { color: tokens.grid } },
    },
  });
}

export function aresTooltip(tokens: AresThemeTokens) {
  return {
    backgroundColor: tokens.raisedHi,
    borderColor: tokens.edge,
    borderWidth: 1,
    className: "ares-chart-tooltip",
    textStyle: { color: tokens.ink, fontSize: 12, fontFamily: tokens.font },
    confine: true,
    transitionDuration: 0.22,
  };
}

export function bevelFill(base: string) {
  return new graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: color.lift(base, 0.2) },
    { offset: 0.45, color: base },
    { offset: 1, color: color.lift(base, -0.24) },
  ]);
}

export function raisedBar(base: string, tokens: AresThemeTokens) {
  return {
    color: bevelFill(base),
    borderColor: tokens.edgeDark,
    borderWidth: 1,
    borderRadius: [tokens.radius, tokens.radius, 0, 0],
    shadowColor: tokens.edgeDark,
    shadowOffsetY: 2,
    shadowBlur: 0,
  };
}

export function areaFill(base: string) {
  return new graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: color.modifyAlpha(base, 0.3) },
    { offset: 1, color: color.modifyAlpha(base, 0.02) },
  ]);
}

export function categoryAxis(tokens: AresThemeTokens, data: string[]) {
  return {
    type: "category" as const,
    data,
    axisLine: { lineStyle: { color: tokens.edgeDark, width: 2 } },
    axisTick: { show: false },
    axisLabel: { color: tokens.ink2, fontSize: 11, fontFamily: tokens.font },
  };
}

export function valueAxis(tokens: AresThemeTokens) {
  return {
    type: "value" as const,
    minInterval: 1,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: tokens.ink2, fontSize: 11, fontFamily: tokens.font },
    splitLine: { lineStyle: { color: tokens.grid } },
  };
}
