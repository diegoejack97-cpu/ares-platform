import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryPanel } from "./memory-panel";
import { OutcomePanel, OutcomeMetricsPanel } from "./outcome-panel";
import {
  memoryConfiguration,
  memoryDocuments,
  memorySaveConfiguration,
  outcomeOpportunity,
  outcomeMetrics,
  outcomeStart,
} from "./intelligence-api";

vi.mock("./intelligence-api", () => ({
  memoryConfiguration: vi.fn(),
  memoryDocuments: vi.fn(),
  memorySaveConfiguration: vi.fn(),
  memoryUpload: vi.fn(),
  memoryRemove: vi.fn(),
  outcomeOpportunity: vi.fn(),
  outcomeMetrics: vi.fn(),
  outcomeStart: vi.fn(),
  outcomeFeedback: vi.fn(),
  outcomeEpisode: vi.fn(),
}));
vi.mock("@/features/auth/auth-context", () => ({
  useAuth: () => ({
    session: {
      user: {
        id: "synthetic",
        app_metadata: { active_tenant_id: "tenant", role: "admin" },
      },
    },
  }),
}));
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(memoryConfiguration).mockResolvedValue({
    can_configure: true,
    configuration: {
      version: 0,
      enabled: false,
      external_consent: false,
      outcomes_enabled: false,
      episodes_enabled: false,
      observation_hours: 48,
      retention_days: 90,
    },
    limits: { memory_storage_bytes: 20971520, embedding_daily_budget_brl: "1" },
    processing: "Processamento externo opt-in.",
  });
  vi.mocked(memoryDocuments).mockResolvedValue({ items: [] });
  vi.mocked(outcomeOpportunity).mockResolvedValue({
    state: "pending",
    evaluation: null,
    chain: null,
  });
});
function mount(node: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {node}
    </QueryClientProvider>,
  );
}

test("external processing is off by default and disabled memory prevents upload", async () => {
  mount(<MemoryPanel />);
  expect(await screen.findByText(/Nenhum documento autorizado/)).toBeVisible();
  await userEvent.click(
    screen.getByText("Configuração e processamento de dados"),
  );
  expect(
    screen.getByRole("checkbox", { name: /Autorizar envio/ }),
  ).not.toBeChecked();
  await userEvent.click(screen.getByText("Adicionar ou atualizar documento"));
  expect(
    screen.getByRole("button", { name: "Salvar documento" }),
  ).toBeDisabled();
});

test("configuration saves the audited consent choice and optimistic version", async () => {
  const config = await memoryConfiguration();
  Object.assign(config.configuration, {
    tenant_id: "synthetic-tenant",
    updated_by: "synthetic-user",
    updated_at: "2026-10-09T12:00:00Z",
  });
  vi.mocked(memorySaveConfiguration).mockResolvedValue(config);
  mount(<MemoryPanel />);
  await screen.findByText(/Nenhum documento autorizado/);
  await userEvent.click(
    screen.getByText("Configuração e processamento de dados"),
  );
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Ativar memória comercial" }),
  );
  await userEvent.type(
    screen.getByLabelText("Justificativa da configuração"),
    "Teste sintético de configuração",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Salvar configuração" }),
  );
  await waitFor(() =>
    expect(memorySaveConfiguration).toHaveBeenCalledWith(
      expect.objectContaining({
        enabled: true,
        external_consent: false,
        expected_version: 0,
        reason: "Teste sintético de configuração",
      }),
      expect.anything(),
    ),
  );
  const command = vi.mocked(memorySaveConfiguration).mock.calls[0][0];
  expect(command).not.toHaveProperty("tenant_id");
  expect(command).not.toHaveProperty("updated_by");
  expect(command).not.toHaveProperty("updated_at");
});

test("missing outcome stays pending and does not request a model", async () => {
  mount(<OutcomePanel opportunityId="synthetic-opportunity" />);
  expect(
    await screen.findByText(/Aguardando resultado observado/),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Solicitar avaliação" }),
  ).not.toBeInTheDocument();
  expect(outcomeStart).not.toHaveBeenCalled();
});

test("metrics show denominators and unavailable response time", async () => {
  const metric = {
    numerator: 0,
    denominator: 0,
    definition: "Sem decisões registradas",
  };
  vi.mocked(outcomeMetrics).mockResolvedValue({
    period_days: 30,
    interventions: 2,
    outcomes_observed: 1,
    pending: 1,
    source: "Sintético",
    coverage: "Todas as intervenções autorizadas",
    adoption: metric,
    rejection: metric,
    execution_failure: metric,
    observed_state_change: metric,
    risk_resolution: metric,
    response_definition: "Sem evento tipado de resposta comercial.",
  });
  mount(<OutcomeMetricsPanel days={30} />);
  expect(await screen.findByText(/2 intervenções/)).toBeVisible();
  expect(screen.getByText(/Sem evento tipado/)).toBeVisible();
  expect(screen.getAllByText("0 / 0")).toHaveLength(5);
});
