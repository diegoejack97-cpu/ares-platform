import { memo, useEffect, useRef } from "react";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  GraphicComponent,
  GridComponent,
  TooltipComponent,
} from "echarts/components";
import {
  init,
  use as registerECharts,
  type ECharts,
  type EChartsCoreOption,
} from "echarts/core";
import { SVGRenderer } from "echarts/renderers";

import { readThemeTokens, registerAresTheme } from "./aresTheme";

registerECharts([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  GraphicComponent,
  TooltipComponent,
  SVGRenderer,
]);

export const AresChart = memo(function AresChart({
  option,
  label,
  className = "",
  physicalAxis = false,
}: {
  option: EChartsCoreOption;
  label: string;
  className?: string;
  physicalAxis?: boolean;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ECharts | null>(null);
  const optionRef = useRef(option);
  const themeRef = useRef(document.documentElement.dataset.theme);

  // Only mounting owns the instance. Refetch and theme changes use the same renderer.
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    registerAresTheme(readThemeTokens());
    const chart = init(host, "ares", { renderer: "svg" });
    chartRef.current = chart;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const render = () => {
      if (chart.isDisposed()) return;
      chart.setOption(
        {
          ...optionRef.current,
          animation: !motion.matches,
          animationDuration: 620,
          animationDurationUpdate: 380,
          animationEasing: "cubicOut",
          animationEasingUpdate: "cubicOut",
          animationDelay: (index: number) => Math.min(index, 5) * 70,
        },
        { notMerge: false, replaceMerge: ["series"], lazyUpdate: true },
      );
    };
    motion.addEventListener("change", render);
    const resize = new ResizeObserver(() => chart.resize());
    resize.observe(host);
    return () => {
      motion.removeEventListener("change", render);
      resize.disconnect();
      chartRef.current = null;
      chart.dispose();
    };
  }, []);

  useEffect(() => {
    optionRef.current = option;
    const chart = chartRef.current;
    if (!chart) return;
    const nextTheme = document.documentElement.dataset.theme;
    if (themeRef.current !== nextTheme) {
      registerAresTheme(readThemeTokens());
      chart.setTheme("ares", { silent: true });
      themeRef.current = nextTheme;
    }
    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    chart.setOption(
      {
        ...option,
        animation: !reduced,
        animationDuration: 620,
        animationDurationUpdate: 380,
        animationEasing: "cubicOut",
        animationEasingUpdate: "cubicOut",
        animationDelay: (index: number) => Math.min(index, 5) * 70,
      },
      { notMerge: false, replaceMerge: ["series"], lazyUpdate: true },
    );
  }, [option]);

  return (
    <div
      className={`ares-chart-host ${physicalAxis ? "chart-physical-axis" : ""} ${className}`}
      ref={hostRef}
      role="img"
      aria-label={label}
    />
  );
});
