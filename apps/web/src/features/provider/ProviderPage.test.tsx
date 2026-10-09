import { cleanup, render, screen, within } from "@testing-library/react";
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
  setInitialAdmin,
  setPackage,
  setTenantStatus,
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
    setInitialAdmin: vi.fn(),
    setPackage: vi.fn(),
    setTenantStatus: vi.fn(),
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
  initial_admin_assigned: true,
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
    agent_slots: 2,
    sentinel_slots: 1,
    ai_daily_budget_brl: "5.000000",
    ai_monthly_budget_brl: "50.000000",
    usd_brl_rate: "5.20000000",
    rate_source: "Contrato sintético",
    updated_at: "2026-09-02T00:00:00Z",
  },
  usage: {
    active_members: 3,
    pending_invitations: 1,
    ai_spend_today_brl: "1.250000",
    ai_spend_month_brl: "12.500000",
    agent_runs_today: 2,
    agent_runs_month: 20,
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
  expect(screen.queryByText("Central Admin")).not.toBeInTheDocument();
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
  expect(screen.queryByText("Empresas")).not.toBeInTheDocument();
});

test("selecting a tenant shows modules, billing and quota with the current values", async () => {
  const user = userEvent.setup();
  render(<ProviderPage />);
  await user.click(await screen.findByRole("button", { name: tenant.name }));
  expect(
    await screen.findByText("Tenant sintético · versão 4"),
  ).toBeInTheDocument();
  expect(screen.getByText("ares_connect: active")).toBeInTheDocument();
  await user.click(screen.getByText("Gerenciamento individual de módulos"));
  // Owning the funnel through ARES Connect excludes ARES CRM until assisted migration.
  const moduleSelect = screen.getByLabelText("Módulo");
  expect(
    within(moduleSelect).getByRole("option", { name: "ARES CRM" }),
  ).toBeDisabled();
  expect(
    within(moduleSelect).getByRole("option", { name: "ARES Connect" }),
  ).toBeEnabled();
  expect(screen.getByLabelText("Novo estado de cobrança")).toHaveValue(
    "past_due",
  );
  expect(screen.getByLabelText("Prazo de tolerância")).toHaveValue(
    "2026-09-30",
  );
  expect(screen.getByLabelText("Licenças contratadas")).toHaveValue(10);
  expect(screen.getByLabelText("Capacidade de agentes ativos")).toHaveValue(2);
  expect(screen.getByLabelText("Capacidade de sentinelas ativas")).toHaveValue(
    1,
  );
  expect(screen.getByLabelText("Reais por dólar (USD/BRL)")).toHaveValue(5.2);
  const summary = screen.getByRole("region", { name: "Resumo do contrato" });
  expect(within(summary).getByText("4 / 10")).toBeInTheDocument();
  expect(within(summary).getByText("1 / 2")).toBeInTheDocument();
  expect(
    within(summary).getByText("2 execuções registradas hoje"),
  ).toBeInTheDocument();
});

test("entitlement changes carry the expected version and surface conflicts", async () => {
  const user = userEvent.setup();
  vi.mocked(setEntitlement).mockRejectedValue(
    new ProviderError(409, "version_conflict"),
  );
  render(<ProviderPage />);
  await user.click(await screen.findByRole("button", { name: tenant.name }));
  await screen.findByText("Tenant sintético · versão 4");
  await user.click(screen.getByText("Gerenciamento individual de módulos"));
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

test("assigning a package includes its expiry, reason, and current version", async () => {
  const user = userEvent.setup();
  vi.mocked(setPackage).mockResolvedValue({ ...tenant, version: 5 });
  render(<ProviderPage />);
  await user.click(await screen.findByRole("button", { name: tenant.name }));
  await screen.findByText("Tenant sintético · versão 4");
  await user.selectOptions(
    screen.getByLabelText("Pacote contratado"),
    "full_connect",
  );
  await user.type(screen.getByLabelText("Válido até"), "2027-12-31T18:00");
  await user.type(
    screen.getByLabelText("Motivo da atribuição ou renovação"),
    "Contrato anual",
  );
  await user.click(
    screen.getByRole("button", { name: "Atribuir ou renovar plano" }),
  );
  expect(
    await screen.findByText("Plano atualizado e auditado."),
  ).toBeInTheDocument();
  expect(setPackage).toHaveBeenCalledWith(tenant.id, {
    package: "full_connect",
    expires_at: new Date("2027-12-31T18:00").toISOString(),
    reason: "Contrato anual",
    expected_version: 4,
  });
});

test("company release stays blocked until billing is active", async () => {
  const user = userEvent.setup();
  render(<ProviderPage />);
  await user.click(await screen.findByRole("button", { name: tenant.name }));
  await screen.findByText("Tenant sintético · versão 4");
  await user.selectOptions(
    screen.getByLabelText("Novo estado da empresa"),
    "active",
  );
  expect(
    screen.getByRole("button", { name: "Salvar liberação" }),
  ).toBeDisabled();
  expect(setTenantStatus).not.toHaveBeenCalled();
});

test("provider assigns the first verified administrator before release", async () => {
  const user = userEvent.setup();
  vi.mocked(tenantConfiguration).mockResolvedValue({
    ...structuredClone(configuration),
    tenant: { ...tenant, status: "suspended" },
    initial_admin_assigned: false,
  });
  vi.mocked(setInitialAdmin).mockResolvedValue({ ...tenant, version: 5 });
  render(<ProviderPage />);
  await user.click(await screen.findByRole("button", { name: tenant.name }));
  await screen.findByText("Tenant sintético · versão 4");
  await user.selectOptions(
    screen.getByLabelText("Novo estado da empresa"),
    "active",
  );
  expect(
    screen.getByRole("button", { name: "Salvar liberação" }),
  ).toBeDisabled();
  await user.type(
    screen.getByLabelText("E-mail do administrador"),
    "gestor@example.com",
  );
  await user.type(
    screen.getByLabelText("Motivo da indicação"),
    "Responsável pelo contrato",
  );
  await user.click(
    screen.getByRole("button", { name: "Indicar administrador" }),
  );
  expect(
    await screen.findByText("Administrador inicial indicado e auditado."),
  ).toBeInTheDocument();
  expect(setInitialAdmin).toHaveBeenCalledWith(tenant.id, {
    email: "gestor@example.com",
    reason: "Responsável pelo contrato",
    expected_version: 4,
  });
});

test("releasing a configured company carries its version and audit reason", async () => {
  const user = userEvent.setup();
  vi.mocked(tenantConfiguration).mockResolvedValue({
    ...structuredClone(configuration),
    tenant: { ...tenant, status: "suspended" },
    billing: { ...configuration.billing!, state: "active" },
  });
  vi.mocked(setTenantStatus).mockResolvedValue({ ...tenant, version: 5 });
  render(<ProviderPage />);
  await user.click(await screen.findByRole("button", { name: tenant.name }));
  await screen.findByText("Tenant sintético · versão 4");
  await user.selectOptions(
    screen.getByLabelText("Novo estado da empresa"),
    "active",
  );
  await user.type(
    screen.getByLabelText("Motivo da liberação ou suspensão"),
    "Contrato habilitado",
  );
  await user.click(screen.getByRole("button", { name: "Salvar liberação" }));
  expect(
    await screen.findByText("Estado da empresa atualizado e auditado."),
  ).toBeInTheDocument();
  expect(setTenantStatus).toHaveBeenCalledWith(tenant.id, {
    status: "active",
    reason: "Contrato habilitado",
    expected_version: 4,
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
