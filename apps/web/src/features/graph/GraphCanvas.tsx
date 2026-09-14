import { useEffect, useRef } from "react";
import { init, use as register } from "echarts/core";
import { GraphChart } from "echarts/charts";
import { SVGRenderer } from "echarts/renderers";
import { readThemeTokens } from "@/charts/aresTheme";
import type { OpportunityGraph } from "@/features/agents/contract";

register([GraphChart, SVGRenderer]);

export default function GraphCanvas({ graph }: { graph: OpportunityGraph }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const chart = init(host.current, undefined, { renderer: "svg" });
    const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const draw = () => {
      const t = readThemeTokens();
      chart.setOption(
        {
          animation: !motion?.matches,
          series: [
            {
              type: "graph",
              layout: "force",
              roam: true,
              draggable: true,
              zoom: 0.8,
              force: {
                repulsion: 450,
                edgeLength: 130,
                gravity: 0.15,
                layoutAnimation: !motion?.matches,
              },
              edgeSymbol: ["none", "arrow"],
              edgeSymbolSize: 7,
              label: {
                show: true,
                position: "bottom",
                color: t.ink,
                fontFamily: t.font,
                fontSize: 12,
              },
              lineStyle: { color: t.ink3, width: 2 },
              data: graph.nodes.map((n) => ({
                id: n.id,
                name: n.label,
                symbolSize: n.id === graph.root_id ? 38 : 28,
                itemStyle: {
                  color:
                    n.kind === "opportunity"
                      ? t.brasa
                      : n.kind === "deal"
                        ? t.jade
                        : t.aco,
                  borderColor: t.ink,
                  borderWidth: 1,
                },
              })),
              links: graph.edges.map((e) => ({
                source: e.src_id,
                target: e.dst_id,
              })),
            },
          ],
        },
        { notMerge: true },
      );
    };
    draw();
    const theme = new MutationObserver(draw);
    theme.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    const size = new ResizeObserver(() => chart.resize());
    size.observe(host.current);
    motion?.addEventListener("change", draw);
    return () => {
      theme.disconnect();
      size.disconnect();
      motion?.removeEventListener("change", draw);
      chart.dispose();
    };
  }, [graph]);
  return (
    <div className="evidence-graph-canvas" ref={host} aria-hidden="true" />
  );
}
