import { memo, useEffect, useRef } from "react";
import {
  BarChart,
  FunnelChart,
  HeatmapChart,
  LineChart,
  PieChart,
  ScatterChart,
  TreemapChart,
} from "echarts/charts";
import {
  GraphicComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
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
  FunnelChart,
  TreemapChart,
  HeatmapChart,
  ScatterChart,
  GridComponent,
  GraphicComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkAreaComponent,
  MarkPointComponent,
  VisualMapComponent,
  SVGRenderer,
]);

export const AresChart = memo(function AresChart({
  option,
  label,
  className = "",
  physicalAxis = false,
  formKey = "",
}: {
  option: EChartsCoreOption;
  label: string;
  className?: string;
  physicalAxis?: boolean;
  /** Changes when the reader picks a different form, forcing a clean redraw. */
  formKey?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ECharts | null>(null);
  const optionRef = useRef(option);
  const themeRef = useRef(document.documentElement.dataset.theme);
  const formKeyRef = useRef(formKey);

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
    // The rail animates the grid track for 380ms, so coalesce that burst into one resize per frame.
    let frame = 0;
    const resize = new ResizeObserver(() => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!chart.isDisposed()) chart.resize();
      });
    });
    resize.observe(host);
    return () => {
      motion.removeEventListener("change", render);
      if (frame) cancelAnimationFrame(frame);
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
      {
        // Switching form swaps axes and series type, so the previous shape must go.
        notMerge: formKey !== formKeyRef.current,
        replaceMerge: ["series", "xAxis", "yAxis", "legend", "visualMap"],
        lazyUpdate: true,
      },
    );
    formKeyRef.current = formKey;
  }, [option, formKey]);

  return (
    <div
      className={`ares-chart-host ${physicalAxis ? "chart-physical-axis" : ""} ${className}`}
      ref={hostRef}
      role="img"
      aria-label={label}
    />
  );
});
