import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ImpactSummary } from "@/features/agents/contract";
import { ImpactPage } from "./ImpactPage";
import { downloadImpact, impactPage, impactSummary } from "./api";

vi.mock("./api", () => ({
  impactSummary: vi.fn(),
  impactPage: vi.fn(),
  downloadImpact: vi.fn(),
}));

const summary: ImpactSummary = {
  window: {
    since: "2026-08-17T10:00:00Z",
    until: "2026-09-16T10:00:00Z",
    days: 30,
  },
  counts: { at_risk: 12, worked: 4 },
  amounts: [
    {
      currency: "BRL",
      observations: 3,
      synthetic_observations: 3,
      sales_observed: 2,
      recovered: 1,
      sale_value: "6000.00",
      ares_influenced_value: "1200.00",
      incremental_value: null,
      freshness_at: "2026-09-16T09:00:00Z",
    },
  ],
  ai_cost: { runs: 5, measured_runs: 0, cost_usd: null },
  source: "Supabase/PostgreSQL — outcomes e trilha de intervenções",
  computed_at: "2026-09-16T10:00:00Z",
  definitions: ["Valor influenciado não prova causalidade."],
};

afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(impactSummary).mockResolvedValue(structuredClone(summary));
  vi.mocked(impactPage).mockResolvedValue({
    items: [
      {
        intervention_id: "40000000-0000-0000-0000-000000000004",
        opportunity_id: "50000000-0000-0000-0000-000000000005",
        correlation_id: "60000000-0000-0000-0000-000000000006",
        status: "closed",
        state_before_ref: "70000000-0000-0000-0000-000000000007",
        state_after_ref: null,
        created_at: "2026-09-10T10:00:00Z",
        closed_at: null,
        result_type: null,
        sale_value: null,
        ares_influenced_value: null,
        incremental_value: null,
        currency: null,
        attribution_level: null,
        attribution_method: null,
        observed_at: null,
      },
    ],
    next_cursor: null,
  });
});

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ImpactPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("synthetic data is disclosed and unproven increments are never shown as zero", async () => {
  mount();
  expect(
    await screen.findByText(/Este relatório contém dados sintéticos/),
  ).toBeInTheDocument();
  expect(screen.getByText("BRL 6.000,00")).toBeInTheDocument();
  expect(screen.getByText("BRL 1.200,00")).toBeInTheDocument();
  expect(screen.getByText("Não comprovado")).toBeInTheDocument();
  expect(
    screen.getByText("0 de 5 execuções com custo medido"),
  ).toBeInTheDocument();
  expect(screen.getByText("Não informado")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Abrir oportunidade" }),
  ).toHaveAttribute(
    "href",
    "/opportunities/50000000-0000-0000-0000-000000000005",
  );
  expect(screen.getByText("Ainda não observado")).toBeInTheDocument();
  expect(screen.getByText("Encerrada")).toBeInTheDocument();
  expect(screen.queryByText("closed")).not.toBeInTheDocument();
});

test("absence of outcomes is explained instead of rendered as zero revenue", async () => {
  vi.mocked(impactSummary).mockResolvedValue({ ...summary, amounts: [] });
  mount();
  expect(
    await screen.findByText(/ausência não representa receita zero/),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/Este relatório contém dados sintéticos/),
  ).not.toBeInTheDocument();
});

test("period change reloads both queries and export uses the selected window", async () => {
  const user = userEvent.setup();
  vi.mocked(downloadImpact).mockResolvedValue(undefined);
  mount();
  await screen.findByText("BRL 6.000,00");
  await user.selectOptions(screen.getByLabelText("Período"), "90");
  expect(impactSummary).toHaveBeenLastCalledWith(90, expect.any(AbortSignal));
  expect(impactPage).toHaveBeenLastCalledWith(
    90,
    null,
    expect.any(AbortSignal),
  );
  await user.click(screen.getByRole("button", { name: "Exportar PDF" }));
  expect(downloadImpact).toHaveBeenCalledWith(90, "pdf");
});

test("denied access shows the server message and hides amounts", async () => {
  vi.mocked(impactSummary).mockRejectedValue(
    new Error("Esta conta não tem acesso a este relatório."),
  );
  mount();
  expect(
    await screen.findByText("Esta conta não tem acesso a este relatório."),
  ).toBeInTheDocument();
  expect(screen.queryByText("Valores por moeda")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Exportar CSV" })).toBeDisabled();
});
