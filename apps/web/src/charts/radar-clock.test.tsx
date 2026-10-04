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
  // The frame now renders a chosen form rather than fixed children.
  ChartFrame: ({
    children,
    forms,
    renderForm,
    hasData = true,
  }: {
    children?: ReactNode;
    forms?: readonly string[];
    renderForm?: (form: string) => ReactNode;
    hasData?: boolean;
  }) => (
    <section>
      {hasData && renderForm ? renderForm(forms?.[0] ?? "column") : children}
    </section>
  ),
  ChartDataTable: () => null,
  ChartLegend: () => null,
}));
vi.mock("@/components/live/live-value", () => ({ LiveValue: () => null }));
// Partial mock: only the token source is stubbed, so every real ramp and
// gradient helper still runs and a new export cannot silently break the suite.
vi.mock("@/charts/aresTheme", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/charts/aresTheme")>();
  return {
    ...actual,
    useThemeTokens: () => ({
      font: "test",
      ink: "#ffffff",
      ink2: "#cccccc",
      ink3: "#aaaaaa",
      well: "#101517",
      panel: "#1a2029",
      raisedHi: "#28323f",
      edge: "#3e4a59",
      edgeHi: "#536276",
      edgeDark: "#080c11",
      grid: "#ffffff12",
      brasa: "#e96943",
      ambar: "#d99022",
      jade: "#3f8f74",
      aco: "#7089a6",
      lilas: "#9a83b5",
      radius: 3,
      bevelLit: 0.19,
      bevelShade: 0.26,
      contour: 0.34,
      rampLit: 0.51,
      rampShade: 0.44,
      lift: 3,
      liftHover: 5,
    }),
  };
});

import { RadarIntelligenceCharts } from "@/features/opportunities/radar-intelligence-charts";
import type { OpportunityAnalytics } from "@/features/opportunities/types";

afterEach(() => {
  cleanup();
  captured.clear();
});

function analytics(
  overrides: Partial<OpportunityAnalytics> = {},
): OpportunityAnalytics {
  return {
    stages: [
      {
        label: "proposal",
        count: 48,
        total: "4891000.00",
        missing: 0,
        currency: "BRL",
      },
      {
        label: "won",
        count: 20,
        total: "2060000.00",
        missing: 0,
        currency: "BRL",
      },
    ],
    signals: [{ label: "follow_up_overdue", count: 30 }],
    sla: [
      { bucket: "overdue", count: 7, total: "1000.00" },
      { bucket: "soon", count: 3, total: null },
    ],
    opened: [{ day: "2026-09-01", count: 4 }],
    activity: [{ day: "2026-09-02", count: 9 }],
    rhythm: [{ weekday: 1, band: 2, count: 5 }],
    points: [
      {
        id: "p1",
        title: "Oportunidade Sintética 060",
        score: "1.0000",
        deal_value: "180000.00",
        currency: "BRL",
        stage: "lost",
        overdue: true,
      },
    ],
    total: 148,
    point_cap: 400,
    source: "ARES Core / Supabase local",
    freshness_at: "2026-09-12T00:00:00Z",
    ...overrides,
  };
}

describe("Radar charts read the server aggregate", () => {
  it("maps SLA buckets in the order the legend declares", () => {
    render(<RadarIntelligenceCharts analytics={analytics()} />);
    const option = [...captured].find(([label]) =>
      label.startsWith("Oportunidades com SLA"),
    )?.[1];
    const series = option?.series as Array<{ data: Array<{ value: number }> }>;
    // Vencido, Próximas 24h, Depois de 24h, Sem prazo válido
    expect(series[0].data.map((item) => item.value)).toEqual([7, 3, 0, 0]);
  });

  it("plots every stage the aggregate reports, not just the loaded page", () => {
    render(<RadarIntelligenceCharts analytics={analytics()} />);
    const option = [...captured].find(([label]) =>
      label.startsWith("Valor observado por etapa"),
    )?.[1];
    const series = option?.series as Array<{ data: Array<{ name: string }> }>;
    expect(series[0].data.map((item) => item.name)).toEqual([
      "Proposta",
      "Ganho",
    ]);
  });

  it("builds matrix points from numerics that arrive as strings", () => {
    render(<RadarIntelligenceCharts analytics={analytics()} />);
    const option = [...captured].find(([label]) =>
      label.startsWith("Relação entre score e valor"),
    )?.[1];
    const series = option?.series as Array<{
      data: Array<{ value: number[] }>;
    }>;
    expect(series[0].data).toHaveLength(1);
    expect(series[0].data[0].value).toEqual([100, 180000]);
  });

  it("renders the empty state when the tenant has no opportunities", () => {
    render(
      <RadarIntelligenceCharts
        analytics={analytics({
          total: 0,
          stages: [],
          points: [],
          signals: [],
          opened: [],
          activity: [],
          rhythm: [],
        })}
      />,
    );
    expect(captured.size).toBe(0);
  });
});
