import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { PortfolioPanel } from "./portfolio-panel";
import { CommercialConfigurationPanel } from "./commercial-configuration";
import {
  getCommercialConfiguration,
  getPortfolioAnalysis,
  saveCommercialConfiguration,
  startPortfolioAnalysis,
} from "./commercial-api";

vi.mock("./commercial-api", () => ({
  getCommercialConfiguration: vi.fn(),
  getPortfolioAnalysis: vi.fn(),
  saveCommercialConfiguration: vi.fn(),
  startPortfolioAnalysis: vi.fn(),
}));
vi.mock("@/features/auth/auth-context", () => ({
  useAuth: () => ({
    session: {
      user: {
        id: "synthetic",
        app_metadata: { active_tenant_id: "synthetic-tenant" },
      },
    },
  }),
}));
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getPortfolioAnalysis).mockResolvedValue({
    state: "not_generated",
    analysis_id: null,
    can_request: true,
    criterion: "urgency",
    currency: null,
    ranking: null,
    briefing: null,
    created_at: null,
    valid_until: null,
    context_ref: null,
    run_ids: [],
    error_code: null,
    source: "Synthetic mirror",
    total: 31,
    currency_totals: [],
    candidates: [],
    coverage_note: "Seleção completa antes do limite de contexto.",
    scope: "tenant",
  });
  vi.mocked(getCommercialConfiguration).mockResolvedValue({
    version: 0,
    can_configure: true,
    available: true,
    config: null,
  });
  vi.mocked(startPortfolioAnalysis).mockResolvedValue({
    id: "analysis",
    reused: false,
  });
  vi.mocked(saveCommercialConfiguration).mockResolvedValue({
    version: 1,
    can_configure: true,
    available: true,
    config: null,
  });
});
function mount(node: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

test("portfolio uses full count and requests value with an explicit currency", async () => {
  mount(<PortfolioPanel />);
  expect(await screen.findByText(/31 negócios no recorte/)).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText("Critério"), "value");
  await userEvent.selectOptions(screen.getByLabelText("Moeda"), "USD");
  await userEvent.click(
    await screen.findByRole("button", { name: "Analisar carteira" }),
  );
  await waitFor(() =>
    expect(startPortfolioAnalysis).toHaveBeenCalledWith({
      criterion: "value",
      currency: "USD",
    }),
  );
});

test("saving scheduled routine sends typed weekdays, exact times and version", async () => {
  mount(<CommercialConfigurationPanel />);
  await userEvent.click(
    await screen.findByLabelText("Ativar análise da carteira"),
  );
  await userEvent.click(
    screen.getByLabelText("Separar Recomendação e Follow-up"),
  );
  await userEvent.type(
    screen.getByLabelText("Motivo da alteração"),
    "Synthetic opt in",
  );
  await userEvent.click(screen.getByRole("button", { name: "Salvar rotina" }));
  await waitFor(() =>
    expect(saveCommercialConfiguration).toHaveBeenCalledWith(
      expect.objectContaining({
        expected_version: 0,
        enabled: true,
        recommendations_enabled: true,
        proactive_enabled: false,
        calendar: {
          days_of_week: [0, 1, 2, 3, 4],
          timezone: "America/Sao_Paulo",
          execution_times: ["09:00"],
        },
      }),
      expect.anything(),
    ),
  );
});

test("company member without admin permission cannot save configuration", async () => {
  vi.mocked(getCommercialConfiguration).mockResolvedValue({
    version: 0,
    can_configure: false,
    available: true,
    config: null,
  });
  mount(<CommercialConfigurationPanel />);
  expect(
    await screen.findByRole("button", { name: "Salvar rotina" }),
  ).toBeDisabled();
  expect(saveCommercialConfiguration).not.toHaveBeenCalled();
});
