import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { SentinelSchedule } from "@/features/agents/contract";
import { account } from "@/features/provider/account-api";
import { SentinelsPage } from "./SentinelsPage";
import {
  createSentinelRule,
  getSentinelCatalog,
  saveSentinelRule,
} from "./api";

vi.mock("./api", () => ({
  getSentinelCatalog: vi.fn(),
  createSentinelRule: vi.fn(),
  saveSentinelRule: vi.fn(),
  archiveSentinelRule: vi.fn(),
}));
vi.mock("@/features/provider/account-api", () => ({ account: vi.fn() }));
vi.mock("@/features/auth/auth-context", () => ({
  useAuth: () => ({
    session: {
      user: { id: "user-1", app_metadata: { active_tenant_id: "tenant-1" } },
    },
  }),
}));

const schedule: SentinelSchedule = {
  rule_id: "SENTINEL-SLA-OVERDUE",
  kind: "sla_overdue",
  title: "SLA vencido",
  definition: "Oportunidade ARES aberta com prazo de SLA vencido.",
  threshold_hours: 0,
  enabled: true,
  interval_minutes: 60,
  start_time_local: "08:00:00",
  timezone: "America/Sao_Paulo",
  next_run_at: "2026-09-29T12:00:00Z",
  last_run_at: "2026-09-29T11:00:00Z",
  last_created_count: 0,
  version: 2,
  updated_at: "2026-09-29T10:00:00Z",
  sentinel_slots: 2,
  can_run: true,
};

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SentinelsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getSentinelCatalog).mockResolvedValue({
    items: [structuredClone(schedule)],
    sentinel_slots: 2,
    active_count: 1,
    timezone: "America/Sao_Paulo",
  });
  vi.mocked(account).mockResolvedValue({ role: "admin" });
  vi.mocked(createSentinelRule).mockResolvedValue(schedule);
  vi.mocked(saveSentinelRule).mockResolvedValue(schedule);
});
afterEach(cleanup);

test("catalog shows rule cards and no repeated findings list", async () => {
  mount();
  expect(
    await screen.findByRole("heading", { name: "SLA vencido" }),
  ).toBeInTheDocument();
  expect(screen.getByText("24 por dia")).toBeInTheDocument();
  expect(screen.queryByText("Achados atuais")).not.toBeInTheDocument();
});

test("administrator creates a typed rule with frequency, time and reason", async () => {
  const user = userEvent.setup();
  mount();
  await screen.findByText("SLA vencido");
  await user.click(screen.getByRole("button", { name: "Criar sentinela" }));
  await user.type(screen.getByLabelText("Nome da regra"), "Sem dono");
  await user.selectOptions(
    screen.getByLabelText("Condição observada"),
    "unassigned",
  );
  await user.clear(screen.getByLabelText("Horas desde a abertura"));
  await user.type(screen.getByLabelText("Horas desde a abertura"), "24");
  await user.selectOptions(screen.getByLabelText("Frequência"), "120");
  await user.clear(screen.getByLabelText("Horário de referência"));
  await user.type(screen.getByLabelText("Horário de referência"), "09:30");
  await user.click(
    screen.getByRole("checkbox", { name: "Ativar esta sentinela" }),
  );
  await user.type(
    screen.getByLabelText("Motivo da alteração"),
    "Revisar oportunidades sem dono",
  );
  await user.click(screen.getByRole("button", { name: "Criar regra" }));
  await waitFor(() =>
    expect(createSentinelRule).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Sem dono",
        kind: "unassigned",
        threshold_hours: 24,
        interval_minutes: 120,
        start_time_local: "09:30",
        enabled: true,
        reason: "Revisar oportunidades sem dono",
      }),
    ),
  );
});

test("non-admin sees cards but cannot create rules", async () => {
  vi.mocked(account).mockResolvedValue({ role: "manager" });
  mount();
  expect(await screen.findByText("SLA vencido")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Criar sentinela" }),
  ).not.toBeInTheDocument();
});

test("capacity stops activation when plan has no free slot", async () => {
  vi.mocked(getSentinelCatalog).mockResolvedValue({
    items: [schedule],
    sentinel_slots: 1,
    active_count: 1,
    timezone: schedule.timezone,
  });
  const user = userEvent.setup();
  mount();
  await screen.findByText("SLA vencido");
  await user.click(screen.getByRole("button", { name: "Criar sentinela" }));
  await user.click(
    screen.getByRole("checkbox", { name: "Ativar esta sentinela" }),
  );
  expect(screen.getByRole("button", { name: "Criar regra" })).toBeDisabled();
  expect(
    screen.getByText(/Pause outra regra antes de ativar/),
  ).toBeInTheDocument();
});
