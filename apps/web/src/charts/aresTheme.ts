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
    bevelLit: Number.parseFloat(token("--bevel-lit")) || 0.19,
    bevelShade: Number.parseFloat(token("--bevel-shade")) || 0.26,
    contour: Number.parseFloat(token("--plot-contour")) || 0.34,
    rampLit: Number.parseFloat(token("--ramp-lit")) || 0.51,
    rampShade: Number.parseFloat(token("--ramp-shade")) || 0.44,
    lift: Number.parseFloat(token("--plot-lift")) || 3,
    liftHover: Number.parseFloat(token("--plot-lift-hover")) || 5,
  };
}

/**
 * zrender's lift() brightens at every level — a negative level multiplies each
 * channel by (1 - level), so lift(base, -0.22) returns a colour 22% lighter.
 * Darkening therefore needs its own helper.
 */
export function shade(base: string, amount: number) {
  const parsed = color.parse(base);
  if (!parsed) return base;
  const scale = 1 - amount;
  return color.stringify(
    [
      Math.round(parsed[0] * scale),
      Math.round(parsed[1] * scale),
      Math.round(parsed[2] * scale),
      parsed[3] ?? 1,
    ],
    "rgba",
  );
}

/** Toward white. Positive lift() is a genuine tint, so it is kept. */
export function tint(base: string, amount: number) {
  return color.lift(base, amount);
}

export type AresThemeTokens = ReturnType<typeof readThemeTokens>;

/** Category identity keeps its colour when a refetch changes the ordering. */
export function categoryColor(label: string, tokens: AresThemeTokens) {
  // Explicit signal identity avoids hash collisions between the dominant signals.
  switch (label) {
    case "Alto valor em risco":
      return tokens.brasa;
    case "Contato inativo":
      return tokens.aco;
    case "Follow-up vencido":
      return tokens.ambar;
    case "Fechamento em risco":
      return tokens.jade;
    case "Proposta parada":
      return tokens.lilas;
    case "proposal":
      return tokens.jade;
    case "qualification":
      return tokens.aco;
    case "negotiation":
      return tokens.ambar;
  }
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
    const observer = new MutationObserver(() => {
      const next = readThemeTokens();
      setTokens((previous) =>
        (Object.keys(next) as Array<keyof AresThemeTokens>).every(
          (key) => previous[key] === next[key],
        )
          ? previous
          : next,
      );
    });
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
    color: [tokens.brasa, tokens.aco, tokens.ambar, tokens.jade, tokens.lilas],
    legend: {
      textStyle: { color: tokens.ink2, fontFamily: tokens.font, fontSize: 11 },
      icon: "rect",
      itemWidth: 8,
      itemHeight: 8,
    },
    axisPointer: {
      lineStyle: { color: tokens.ink3, type: "dashed", width: 1 },
      label: { backgroundColor: tokens.raisedHi, color: tokens.ink },
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: tokens.edge, width: 1 } },
      axisTick: { show: false },
      axisLabel: { color: tokens.ink2, fontSize: 11 },
      splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: tokens.ink2, fontSize: 11 },
      splitLine: { lineStyle: { color: tokens.grid, type: "dashed" } },
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
    padding: [10, 12],
    extraCssText:
      "max-width: min(340px, 80vw); white-space: normal; line-height: 1.6;",
  };
}

/**
 * One light source, above. The ramp spans the full height so it is resolvable on a
 * 15px bar, and its strength comes from the theme so light and dark stay siblings.
 */
export function bevelFill(base: string, tokens: AresThemeTokens) {
  return new graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: tint(base, tokens.bevelLit) },
    { offset: 0.42, color: base },
    { offset: 1, color: shade(base, tokens.bevelShade) },
  ]);
}

export function raisedBar(base: string, tokens: AresThemeTokens) {
  return {
    color: bevelFill(base, tokens),
    borderColor: shade(base, tokens.contour),
    borderWidth: 1,
    borderRadius: [tokens.radius, tokens.radius, 0, 0],
    shadowColor: tokens.edgeDark,
    shadowOffsetY: tokens.lift,
    shadowBlur: 0,
  };
}

/**
 * Ordered categories — funnel stages, tiers, buckets — take one hue in monotone
 * steps, so the reader sees the order in the colour. Nominal categories must not
 * use this: colouring a bar by its own value spends the identity channel on what
 * the bar length already shows.
 */
export function ordinalRamp(
  base: string,
  count: number,
  tokens: AresThemeTokens,
) {
  if (count <= 1) return [base];
  const span = tokens.rampLit + tokens.rampShade;
  return Array.from({ length: count }, (_, index) => {
    const amount = tokens.rampLit - (index / (count - 1)) * span;
    return amount >= 0 ? tint(base, amount) : shade(base, -amount);
  });
}

/** One series is the point and the rest are context: accent it, recede the others. */
export function emphasisRamp(
  base: string,
  count: number,
  focusIndex: number,
  tokens: AresThemeTokens,
) {
  return Array.from({ length: count }, (_, index) =>
    index === focusIndex ? base : tokens.aco,
  );
}

/** The hover step is the next rung of the same ramp, never an arbitrary jump. */
export function raisedBarEmphasis(tokens: AresThemeTokens) {
  return {
    itemStyle: { shadowOffsetY: tokens.liftHover, shadowBlur: 0 },
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
    axisLine: { lineStyle: { color: tokens.edge, width: 1 } },
    axisTick: { show: false },
    axisLabel: {
      color: tokens.ink2,
      fontSize: 11,
      fontFamily: tokens.font,
      hideOverlap: true,
    },
  };
}

export function valueAxis(tokens: AresThemeTokens) {
  return {
    type: "value" as const,
    minInterval: 1,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: tokens.ink2, fontSize: 11, fontFamily: tokens.font },
    splitLine: { lineStyle: { color: tokens.grid, type: "dashed" as const } },
  };
}
