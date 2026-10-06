import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { RadarPage } from "./radar-page";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: vi
        .fn()
        .mockResolvedValue({ data: { session: { access_token: "test" } } }),
    },
  },
}));
vi.mock("./risk-distribution-chart", () => ({
  RiskDistributionChart: () => <div aria-label="Distribuição por prioridade" />,
}));
vi.mock("./radar-intelligence-charts", () => ({
  RadarIntelligenceCharts: () => <div aria-label="Análises do Radar" />,
}));

test.each([false, true])(
  "reveals the priority queue and loads subsequent API pages (paginated=%s)",
  async (paginated) => {
    const baseItem = {
      opportunity_type: "revenue_recovery",
      state: "prioritized",
      // The API serialises numerics as strings; the fixture must match.
      score: "0.92",
      priority: 0,
      owner_user_id: null,
      sla_at: "2026-09-02T16:00:00Z",
      opened_at: "2026-09-02T12:00:00Z",
      updated_at: "2026-09-02T12:00:00Z",
      version: 2,
      signal_count: 8,
      primary_signal_type: "follow_up_overdue",
      score_version: "m2.1",
      score_breakdown: { severity: { value: 0.45, weight: 0.45 } },
      correlation_id: "corr",
      deal_id: "deal",
      external_id: "crm-42",
      external_stage: "proposal",
      deal_value: "125000.00",
      currency: "BRL",
      last_activity_at: "2026-09-02T12:00:00Z",
    };
    const list = {
      items: Array.from({ length: paginated ? 25 : 7 }, (_, index) => ({
        ...baseItem,
        id: `op-${index + 1}`,
        title:
          index === 0 ? "Expansão Serra Metais" : `Oportunidade ${index + 1}`,
      })),
      next_cursor: paginated ? "opaque-next-page" : null,
      source: "ARES Core / Supabase local",
      freshness_at: "2026-09-02T12:00:00Z",
    };
    const aggregate = {
      stages: [],
      signals: [],
      sla: [],
      opened: [],
      activity: [],
      rhythm: [],
      points: [],
      total: 7,
      point_cap: 400,
      source: "ARES Core / Supabase local",
      freshness_at: "2026-09-02T12:00:00Z",
    };
    const nextPage = {
      ...list,
      // Repeat the boundary item to exercise deduplication across pages.
      items: [
        list.items[24],
        ...[26, 27].map((number) => ({
          ...baseItem,
          id: `op-${number}`,
          title: `Oportunidade ${number}`,
        })),
      ],
      next_cursor: null,
    };
    const sentinels = {
      items: [
        {
          id: "finding-1",
          opportunity_id: "op-1",
          rule_id: "SENTINEL-SLA-OVERDUE",
          rule_version: "1",
          due_at: "2026-09-02T16:00:00Z",
          detected_at: "2026-09-03T08:00:00Z",
          evidence: { sla_at: "2026-09-02T16:00:00Z" },
          correlation_id: "corr",
          title: "Expansão Serra Metais",
          state: "prioritized",
          priority: 0,
        },
      ],
      truncated: false,
      rule: {
        id: "SENTINEL-SLA-OVERDUE",
        version: "1",
        definition: "SLA vencido",
      },
      source: "ARES Core / oportunidades e evidências persistidas",
      freshness_at: "2026-09-03T08:00:00Z",
      checked_at: "2026-09-03T08:00:00Z",
    };
    // A Response body reads once, so each call needs its own, routed by URL.
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              String(input).includes("/analytics")
                ? aggregate
                : String(input).includes("/sentinels")
                  ? sentinels
                  : String(input).includes("cursor=opaque-next-page")
                    ? nextPage
                    : list,
            ),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        ),
      );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <RadarPage />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", { name: "Expansão Serra Metais" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Analisar oportunidade" }),
    ).toHaveAttribute("href", "/opportunities/op-1");
    expect(
      screen.queryByRole("heading", { name: "Sentinelas" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText(/Follow-up vencido/).length).toBeGreaterThan(0);
    expect(screen.getByText("Observação ≠ causalidade")).toBeInTheDocument();
    const queue = within(
      screen.getByRole("region", { name: "Fila de oportunidades com rolagem" }),
    );
    expect(queue.getAllByLabelText("Score 92 de 100")).toHaveLength(5);
    expect(
      screen.getAllByText("ARES Core / Supabase local", { exact: false })
        .length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByText(
        paginated
          ? /Exibindo 5 de 25 oportunidades carregadas/
          : "Exibindo 5 de 7 oportunidades",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Oportunidade 6")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Carregar próximas 5" }),
    );

    expect(await screen.findByText("Oportunidade 6")).toBeInTheDocument();
    if (paginated) {
      for (let batch = 0; batch < 4; batch++) {
        await userEvent.click(
          screen.getByRole("button", { name: "Carregar próximas 5" }),
        );
      }
      expect(await screen.findByText("Oportunidade 27")).toBeInTheDocument();
      expect(
        screen.getByText("Exibindo 27 de 27 oportunidades"),
      ).toBeInTheDocument();
      expect(queue.getAllByLabelText("Score 92 de 100")).toHaveLength(27);
      expect(
        fetch.mock.calls.filter(([url]) =>
          String(url).includes("cursor=opaque-next-page"),
        ),
      ).toHaveLength(1);
      expect(
        screen.queryByRole("button", { name: "Carregar próximas 5" }),
      ).not.toBeInTheDocument();
    } else {
      expect(
        screen.getByText("Exibindo 7 de 7 oportunidades"),
      ).toBeInTheDocument();
    }
  },
);
