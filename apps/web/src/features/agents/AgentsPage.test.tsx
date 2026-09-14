import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { AgentsPage } from "./AgentsPage";
import { AgentReadError, getAgents } from "./api";
import type { AgentSummary } from "./contract";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  getAgents: vi.fn(),
}));
vi.mock("@/features/auth/auth-context", () => ({
  useAuth: () => ({
    session: {
      user: {
        id: "test-user",
        app_metadata: { active_tenant_id: "test-tenant" },
      },
    },
  }),
}));
const summary: AgentSummary = {
  items: [
    {
      agent_name: "follow-up+triage",
      agent_version: "m3.1",
      generation_mode: "deterministic_fallback",
      model_id: null,
      runs: 2,
      running: 0,
      succeeded: 0,
      degraded: 2,
      failed: 0,
      latency_samples: 2,
      latency_p95_ms: 1200,
      last_run_at: "2026-09-12T10:00:00Z",
      cost_usd: null,
      cost_status: "not_instrumented",
      autonomy: "proposal_only",
    },
  ],
  window: {
    since: "2026-08-13T10:00:00Z",
    until: "2026-09-12T10:00:00Z",
    days: 30,
  },
  source: "agent_runs",
  freshness_at: "2026-09-12T10:00:00Z",
  latency_definition: "run_wall_time_ms",
  limitations: [],
};
afterEach(cleanup);
test("measured subtotal stays explicitly partial when historical runs have no usage", async () => {
  const measured = structuredClone(summary);
  Object.assign(measured.items[0], {
    cost_usd: 0.00056,
    cost_status: "partial",
    cost_samples: 1,
    usage_samples: 1,
    input_tokens: 1000,
    output_tokens: 200,
    not_called: 0,
  });
  vi.mocked(getAgents).mockResolvedValue(measured);
  mount();
  expect(
    await screen.findByText("Subtotal parcial · 1 execuções"),
  ).toBeInTheDocument();
  expect(screen.getByText("1.000 entrada / 200 saída")).toBeInTheDocument();
  expect(screen.getByText("0,000560")).toBeInTheDocument();
});
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getAgents).mockResolvedValue(structuredClone(summary));
});
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
test("shows fallback, unknown cost and recorded latency without inventing successful model runs", async () => {
  mount();
  expect(await screen.findByText("Follow-up e Triagem")).toBeInTheDocument();
  expect(screen.getByText("REGRA DETERMINÍSTICA")).toBeInTheDocument();
  expect(screen.getByText("Não informado")).toBeInTheDocument();
  expect(screen.getByText("1,2 s")).toBeInTheDocument();
  expect(screen.queryByText("US$ 0,00")).not.toBeInTheDocument();
});
test("period selection loads the requested window and displays its empty state", async () => {
  const user = userEvent.setup();
  mount();
  await screen.findByText("Follow-up e Triagem");
  vi.mocked(getAgents).mockResolvedValue({
    ...summary,
    items: [],
    window: { ...summary.window, days: 7 },
  });
  await user.selectOptions(screen.getByLabelText("Período"), "7");
  expect(
    await screen.findByText("Nenhuma execução neste período"),
  ).toBeInTheDocument();
  expect(getAgents).toHaveBeenLastCalledWith(7, expect.any(AbortSignal));
  expect(
    screen.getByRole("link", { name: "Abrir Radar ARES" }),
  ).toHaveAttribute("href", "/radar");
});
test("revoked access hides previously cached metrics and shows correlation", async () => {
  const user = userEvent.setup();
  mount();
  await screen.findByText("Follow-up e Triagem");
  vi.mocked(getAgents).mockRejectedValue(
    new AgentReadError(403, "test-correlation"),
  );
  await user.click(screen.getByRole("button", { name: "Atualizar leitura" }));
  expect(await screen.findByText("Acesso indisponível")).toBeInTheDocument();
  expect(screen.queryByText("Follow-up e Triagem")).not.toBeInTheDocument();
  expect(screen.getByText("Correlação: test-correlation")).toBeInTheDocument();
});
test("pending fetch shows structural loading, never fabricated zero metrics", () => {
  vi.mocked(getAgents).mockReturnValue(new Promise(() => {}));
  mount();
  expect(
    screen.getByRole("status", { name: "Carregando execuções dos agentes" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Nenhuma execução neste período"),
  ).not.toBeInTheDocument();
});
