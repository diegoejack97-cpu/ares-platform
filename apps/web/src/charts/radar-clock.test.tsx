import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EChartsCoreOption } from "echarts/core";
import type { ReactNode } from "react";

const captured = vi.hoisted(() => new Map<string, EChartsCoreOption>());
vi.mock("@/charts/AresChart", () => ({
  AresChart: ({
    option,
    label,
  }: {
    option: EChartsCoreOption;
    label: string;
  }) => {
    captured.set(label, option);
    return <div aria-label={label} />;
  },
}));
vi.mock("@/charts/ChartFrame", () => ({
  ChartFrame: ({ children }: { children: ReactNode }) => (
    <section>{children}</section>
  ),
  ChartDataTable: () => null,
  ChartLegend: () => null,
}));
vi.mock("@/components/live/live-value", () => ({ LiveValue: () => null }));
vi.mock("@/charts/aresTheme", () => {
  const tokens = {
    font: "test",
    ink: "currentColor",
    ink2: "currentColor",
    edgeDark: "currentColor",
    well: "currentColor",
    brasa: "currentColor",
    ambar: "currentColor",
    jade: "currentColor",
    aco: "currentColor",
    lilas: "currentColor",
    radius: 3,
    bevelLit: 0.19,
    bevelShade: 0.26,
    contour: 0.34,
    lift: 3,
    liftHover: 5,
  };
  return {
    useThemeTokens: () => tokens,
    aresTooltip: () => ({}),
    bevelFill: (value: string) => value,
    categoryAxis: (_tokens: unknown, data: string[]) => ({ data }),
    categoryColor: () => "currentColor",
    raisedBar: () => ({}),
    raisedBarEmphasis: () => ({}),
    shade: (value: string) => value,
    tint: (value: string) => value,
    valueAxis: () => ({}),
  };
});

import { RadarIntelligenceCharts } from "@/features/opportunities/radar-intelligence-charts";
import type { OpportunityListItem } from "@/features/opportunities/types";

afterEach(() => {
  cleanup();
  captured.clear();
});

describe("Radar clock redraw boundaries", () => {
  it("changes only the SLA option when a real deadline moves between buckets", () => {
    const now = Date.parse("2026-09-07T12:00:00Z");
    const items = [
      {
        id: "clock-fixture",
        external_stage: "Proposta",
        currency: "BRL",
        deal_value: "1000.00",
        primary_signal_type: "follow_up_overdue",
        sla_at: new Date(now + 5000).toISOString(),
      },
    ] as OpportunityListItem[];
    const { rerender } = render(
      <RadarIntelligenceCharts items={items} now={now} />,
    );
    const initial = new Map(captured);
    rerender(<RadarIntelligenceCharts items={items} now={now + 1000} />);
    for (const [label, option] of initial)
      expect(captured.get(label)).toBe(option);
    rerender(<RadarIntelligenceCharts items={items} now={now + 6000} />);
    for (const [label, option] of initial) {
      if (label.startsWith("Oportunidades com SLA")) {
        expect(captured.get(label)).not.toBe(option);
        const series = captured.get(label)?.series as Array<{
          data: Array<{ value: number }>;
        }>;
        expect(series[0].data.map((item) => item.value)).toEqual([1, 0, 0, 0]);
      } else expect(captured.get(label)).toBe(option);
    }
  });
});
