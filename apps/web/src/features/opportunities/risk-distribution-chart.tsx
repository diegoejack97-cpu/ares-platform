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
      chart.setOption({
        animation: false,
        grid: { left: 30, right: 16, top: 8, bottom: 28 },
        xAxis: {
          type: "category",
          data: ["Crítica", "Alta", "Média", "Baixa"],
        },
        yAxis: { type: "value", minInterval: 1 },
        series: [{ type: "bar", data: counts, barWidth: 24 }],
        color: ["#2f6b59"],
        tooltip: { trigger: "axis" },
      });
      const resize = () => chart.resize();
      window.addEventListener("resize", resize);
      cleanup = () => {
        window.removeEventListener("resize", resize);
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
