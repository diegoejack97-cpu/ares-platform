import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { TenantConfiguration } from "@/features/agents/contract";
import { ProviderPage } from "./ProviderPage";
import {
  listTenants,
  providerAuth,
  ProviderError,
  setBilling,
  setEntitlement,
  tenantConfiguration,
} from "./api";

vi.mock("./api", () => {
  class ProviderError extends Error {
    status: number;
    correlationId?: string;
    constructor(status: number, code: string, correlationId?: string) {
      super(
        status === 401 || status === 403
          ? "Esta conta não tem acesso de provedor. Use a conta dedicada."
          : code === "funnel_migration_required"
            ? "A troca de dono do funil exige migração assistida."
            : "A configuração mudou ou conflita com outro registro. Recarregue antes de salvar.",
      );
      this.status = status;
      this.correlationId = correlationId;
    }
  }
  return {
    ProviderError,
    providerAuth: {
      auth: {
        getSession: vi.fn(),
        onAuthStateChange: vi.fn(() => ({
          data: { subscription: { unsubscribe: vi.fn() } },
        })),
        signInWithPassword: vi.fn(),
        signOut: vi.fn(),
      },
    },
    listTenants: vi.fn(),
    tenantConfiguration: vi.fn(),
    createTenant: vi.fn(),
    setEntitlement: vi.fn(),
    setBilling: vi.fn(),
    setQuota: vi.fn(),
  };
});

const tenant = {
  id: "30000000-0000-0000-0000-000000000006",
  name: "Tenant sintético",
  slug: "tenant-sintetico",
  status: "active",
  version: 4,
  created_at: "2026-09-15T12:00:00Z",
  updated_at: "2026-09-15T12:00:00Z",
};
const configuration: TenantConfiguration = {
  tenant,
  entitlements: [
    {
      module: "ares_connect",
      status: "active",
      granted_at: tenant.created_at,
      expires_at: null,
    },
  ],
  billing: {
    state: "past_due",
    due_since: "2026-09-01",
    grace_until: "2026-09-30",
    reason: "Fatura em aberto",
    changed_at: "2026-09-02T00:00:00Z",
  },
  quota: {
    seats_limit: 10,
    ai_daily_budget_brl: "5.000000",
    ai_monthly_budget_brl: "50.000000",
    usd_brl_rate: "5.20000000",
    rate_source: "Contrato sintético",
    updated_at: "2026-09-02T00:00:00Z",
  },
};

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(providerAuth.auth.getSession).mockResolvedValue({
    data: { session: { user: { id: "operator" } } },
  } as never);
  vi.mocked(listTenants).mockResolvedValue({
    items: [tenant],
    next_cursor: null,
  });
  vi.mocked(tenantConfiguration).mockResolvedValue(
    structuredClone(configuration),
  );
});

test("without a dedicated session only the provider login is offered", async () => {
  vi.mocked(providerAuth.auth.getSession).mockResolvedValue({
    data: { session: null },
  } as never);
  render(<ProviderPage />);
  expect(
    await screen.findByRole("heading", { name: "Acesso do provedor" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("Painel do provedor")).not.toBeInTheDocument();
  expect(listTenants).not.toHaveBeenCalled();
});

test("a product account is denied and the directory stays hidden", async () => {
  vi.mocked(listTenants).mockRejectedValue(
    new ProviderError(403, "provider_access_denied", "corr-1"),
  );
  render(<ProviderPage />);
  expect(
    await screen.findByText(
      "Esta conta não tem acesso de provedor. Use a conta dedicada.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("Correlação: corr-1")).toBeInTheDocument();
  expect(screen.queryByText("Tenants")).not.toBeInTheDocument();
});

test("selecting a tenant shows modules, billing and quota with the current values", async () => {
  const user = userEvent.setup();
  render(<ProviderPage />);
  await user.click(await screen.findByRole("button", { name: tenant.name }));
  expect(
    await screen.findByText("Tenant sintético · versão 4"),
  ).toBeInTheDocument();
  expect(screen.getByText("ares_connect: active")).toBeInTheDocument();
  // Owning the funnel through ARES Connect excludes ARES CRM until assisted migration.
  expect(screen.getByRole("option", { name: "ARES CRM" })).toBeDisabled();
  expect(screen.getByRole("option", { name: "ARES Connect" })).toBeEnabled();
  expect(screen.getByLabelText("Novo estado de cobrança")).toHaveValue(
    "past_due",
  );
  expect(screen.getByLabelText("Prazo de tolerância")).toHaveValue(
    "2026-09-30",
  );
  expect(screen.getByLabelText("Licenças contratadas")).toHaveValue(10);
  expect(screen.getByLabelText("Reais por dólar (USD/BRL)")).toHaveValue(5.2);
});

test("entitlement changes carry the expected version and surface conflicts", async () => {
  const user = userEvent.setup();
  vi.mocked(setEntitlement).mockRejectedValue(
    new ProviderError(409, "version_conflict"),
  );
  render(<ProviderPage />);
  await user.click(await screen.findByRole("button", { name: tenant.name }));
  await screen.findByText("Tenant sintético · versão 4");
  await user.selectOptions(screen.getByLabelText("Módulo"), "stellar");
  await user.selectOptions(
    screen.getByLabelText("Estado do módulo"),
    "suspended",
  );
  await user.type(
    screen.getByLabelText("Motivo da alteração"),
    "Suspensão contratual",
  );
  await user.click(screen.getByRole("button", { name: "Salvar módulo" }));
  expect(
    await screen.findByText(
      "A configuração mudou ou conflita com outro registro. Recarregue antes de salvar.",
    ),
  ).toBeInTheDocument();
  expect(setEntitlement).toHaveBeenCalledWith(tenant.id, {
    module: "stellar",
    status: "suspended",
    reason: "Suspensão contratual",
    expected_version: 4,
    expires_at: null,
  });
});

test("billing degradation requires dates and is submitted with the tenant version", async () => {
  const user = userEvent.setup();
  vi.mocked(setBilling).mockResolvedValue({ ...tenant, version: 5 });
  render(<ProviderPage />);
  await user.click(await screen.findByRole("button", { name: tenant.name }));
  await screen.findByText("Tenant sintético · versão 4");
  await user.selectOptions(
    screen.getByLabelText("Novo estado de cobrança"),
    "degraded",
  );
  await user.type(
    screen.getByLabelText("Motivo da cobrança"),
    "Prazo encerrado",
  );
  await user.click(screen.getByRole("button", { name: "Salvar cobrança" }));
  expect(
    await screen.findByText("Cobrança atualizada e auditada."),
  ).toBeInTheDocument();
  expect(setBilling).toHaveBeenCalledWith(tenant.id, {
    state: "degraded",
    due_since: "2026-09-01",
    grace_until: "2026-09-30",
    reason: "Prazo encerrado",
    expected_version: 4,
  });
});
