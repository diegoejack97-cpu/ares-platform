import { useEffect, useRef } from "react";

import type { OpportunityListItem } from "./types";

export function RiskDistributionChart({
  items,
}: {
  items: OpportunityListItem[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    let disposed = false;
    let cleanup = () => {};
    void import("echarts").then((echarts) => {
      if (disposed || !ref.current) return;
      const chart = echarts.init(ref.current, undefined, { renderer: "svg" });
      const counts = [0, 1, 2, 3].map(
        (priority) => items.filter((item) => item.priority === priority).length,
      );
      const render = () => {
        const styles = getComputedStyle(document.documentElement);
        const token = (name: string, fallback: string) =>
          styles.getPropertyValue(name).trim() || fallback;
        const reducedMotion = window.matchMedia(
          "(prefers-reduced-motion: reduce)",
        ).matches;
        chart.setOption(
          {
            animation: !reducedMotion,
            animationDuration: 620,
            animationDurationUpdate: 380,
            grid: { left: 30, right: 16, top: 8, bottom: 28 },
            textStyle: { color: token("--foreground", "#18272b") },
            xAxis: {
              type: "category",
              data: ["Crítica", "Alta", "Média", "Baixa"],
              axisLabel: { color: token("--muted-foreground", "#66736f") },
              axisLine: {
                lineStyle: { color: token("--border", "#d5d8d1") },
              },
              axisTick: { show: false },
            },
            yAxis: {
              type: "value",
              minInterval: 1,
              axisLabel: { color: token("--muted-foreground", "#66736f") },
              splitLine: {
                lineStyle: {
                  color: token("--border", "#d5d8d1"),
                  type: "dashed",
                },
              },
            },
            series: [
              {
                type: "bar",
                data: counts,
                barWidth: 24,
                itemStyle: { borderRadius: [2, 2, 0, 0] },
              },
            ],
            color: [token("--chart-1", "#2f6b59")],
            tooltip: {
              trigger: "axis",
              backgroundColor: token("--card", "#fbfaf6"),
              borderColor: token("--border", "#d5d8d1"),
              textStyle: { color: token("--foreground", "#18272b") },
            },
          },
          { notMerge: true },
        );
      };
      render();
      const resizeObserver = new ResizeObserver(() => chart.resize());
      resizeObserver.observe(ref.current);
      const themeObserver = new MutationObserver(render);
      themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["class", "data-theme"],
      });
      cleanup = () => {
        resizeObserver.disconnect();
        themeObserver.disconnect();
        chart.dispose();
      };
    });
    return () => {
      disposed = true;
      cleanup();
    };
  }, [items]);
  return (
    <div
      ref={ref}
      className="risk-chart"
      role="img"
      aria-label="Distribuição acessível na tabela abaixo por prioridade"
    />
  );
}
