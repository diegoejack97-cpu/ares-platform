import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";

import { RadarPage } from "./radar-page";

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

test("renders intelligence context and reveals the priority queue in batches of five", async () => {
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
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        items: Array.from({ length: 7 }, (_, index) => ({
          ...baseItem,
          id: `op-${index + 1}`,
          title:
            index === 0 ? "Expansão Serra Metais" : `Oportunidade ${index + 1}`,
        })),
        next_cursor: null,
        source: "ARES Core / Supabase local",
        freshness_at: "2026-09-02T12:00:00Z",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
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
  expect(screen.getAllByText(/Follow-up vencido/).length).toBeGreaterThan(0);
  expect(screen.getByText("Observação ≠ causalidade")).toBeInTheDocument();
  const queue = within(
    screen.getByRole("region", { name: "Fila de oportunidades com rolagem" }),
  );
  expect(queue.getAllByLabelText("Score 92 de 100")).toHaveLength(5);
  expect(
    screen.getAllByText("ARES Core / Supabase local", { exact: false }).length,
  ).toBeGreaterThan(0);
  expect(screen.getByText("Exibindo 5 de 7 oportunidades")).toBeInTheDocument();
  expect(screen.queryByText("Oportunidade 6")).not.toBeInTheDocument();

  await userEvent.click(
    screen.getByRole("button", { name: "Carregar próximas 5" }),
  );

  expect(await screen.findByText("Oportunidade 6")).toBeInTheDocument();
  expect(screen.getByText("Exibindo 7 de 7 oportunidades")).toBeInTheDocument();
});
