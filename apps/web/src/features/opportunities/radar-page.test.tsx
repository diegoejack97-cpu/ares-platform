import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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

test("renders explainable score, SLA, source, and non-causal value language", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        items: [
          {
            id: "op-1",
            opportunity_type: "revenue_recovery",
            state: "prioritized",
            score: 0.92,
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
            title: "Expansão Serra Metais",
            external_id: "crm-42",
            external_stage: "proposal",
            deal_value: 125000,
            currency: "BRL",
            last_activity_at: "2026-09-02T12:00:00Z",
          },
        ],
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

  expect(await screen.findByText("Expansão Serra Metais")).toBeInTheDocument();
  expect(screen.getByText("Follow-up vencido")).toBeInTheDocument();
  expect(screen.getByText(/não afirma causalidade/i)).toBeInTheDocument();
  expect(screen.getByLabelText("Score 92 de 100")).toBeInTheDocument();
  expect(
    screen.getByText("ARES Core / Supabase local", { exact: false }),
  ).toBeInTheDocument();
});
