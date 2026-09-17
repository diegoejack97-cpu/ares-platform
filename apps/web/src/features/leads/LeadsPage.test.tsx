import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { LeadCandidate, LeadRecord } from "@/features/agents/contract";
import { LeadsPage } from "./LeadsPage";
import { candidates, createIntake, listLeads, resolveLead } from "./api";

vi.mock("./api", () => ({
  listLeads: vi.fn(),
  createIntake: vi.fn(),
  candidates: vi.fn(),
  resolveLead: vi.fn(),
}));

const lead: LeadRecord = {
  id: "10000000-0000-0000-0000-000000000001",
  name: "Maria Sintética",
  email: "maria@example.invalid",
  phone: null,
  status: "pending",
  version: 1,
  owner_id: "user-1",
  target_subject_id: null,
  external_id: null,
  correlation_id: "20000000-0000-0000-0000-000000000002",
  created_at: "2026-09-16T10:00:00Z",
};
const candidate: LeadCandidate = {
  id: "30000000-0000-0000-0000-000000000003",
  display_name: "Maria Sintetica",
  score: 0.92,
  reasons: ["Nome semelhante", "E-mail idêntico"],
};

afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listLeads).mockResolvedValue({
    items: [lead],
    next_cursor: null,
    can_create: true,
  });
  vi.mocked(candidates).mockResolvedValue([candidate]);
});

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LeadsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const queueRow = async (name: string) =>
  (await screen.findByText(name, { selector: ".record-row strong" })).closest(
    "button",
  )!;
const review = () => within(screen.getByRole("region", { name: /^Revisar/ }));

test("intake sends normalised contacts with a per-form idempotency key", async () => {
  const user = userEvent.setup();
  vi.mocked(createIntake).mockResolvedValue({ ...lead, id: "new" });
  mount();
  await queueRow(lead.name);
  await user.type(screen.getByLabelText("Nome do lead"), "Novo Lead");
  await user.type(
    screen.getByLabelText("Telefone do lead"),
    "+55 11 99999-0000",
  );
  await user.click(screen.getByRole("button", { name: "Enviar para triagem" }));
  expect(createIntake).toHaveBeenCalledTimes(1);
  const body = vi.mocked(createIntake).mock.calls[0][0];
  expect(body).toMatchObject({
    name: "Novo Lead",
    email: null,
    phone: "+55 11 99999-0000",
  });
  expect(body.idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
});

test("intake requires at least one contact before calling the API", async () => {
  const user = userEvent.setup();
  mount();
  await queueRow(lead.name);
  await user.type(screen.getByLabelText("Nome do lead"), "Sem contato");
  await user.click(screen.getByRole("button", { name: "Enviar para triagem" }));
  expect(
    await screen.findByText(
      "Informe pelo menos um contato: e-mail ou telefone.",
    ),
  ).toBeInTheDocument();
  expect(createIntake).not.toHaveBeenCalled();
});

test("queue rows show contact and a readable status, never the raw code", async () => {
  mount();
  const row = await queueRow(lead.name);
  expect(within(row).getByText("maria@example.invalid")).toBeInTheDocument();
  expect(within(row).getByText("Pendente")).toBeInTheDocument();
  expect(within(row).queryByText("pending")).not.toBeInTheDocument();
});

test("review lists candidates and merge needs both a target and a reason", async () => {
  const user = userEvent.setup();
  vi.mocked(resolveLead).mockResolvedValue({
    ...lead,
    status: "merged",
    version: 2,
  });
  mount();
  await user.click(await queueRow(lead.name));
  const panel = review();
  expect(await panel.findByText("Maria Sintetica")).toBeInTheDocument();
  expect(panel.getByText("92%")).toBeInTheDocument();
  expect(panel.getByText("Nome semelhante")).toBeInTheDocument();
  expect(panel.getByText("E-mail idêntico")).toBeInTheDocument();
  const merge = panel.getByRole("button", { name: "Mesclar com selecionado" });
  expect(merge).toBeDisabled();
  await user.type(panel.getByLabelText("Motivo da decisão"), "Mesmo contato");
  expect(merge).toBeDisabled();
  await user.click(panel.getByRole("radio"));
  expect(merge).toBeEnabled();
  await user.click(merge);
  expect(resolveLead).toHaveBeenCalledWith(lead.id, {
    action: "merge",
    reason: "Mesmo contato",
    target_subject_id: candidate.id,
    expected_version: 1,
  });
});

test("merged leads offer undo and no longer offer create, merge or discard", async () => {
  const user = userEvent.setup();
  vi.mocked(listLeads).mockResolvedValue({
    items: [{ ...lead, status: "merged", version: 2 }],
    next_cursor: null,
    can_create: true,
  });
  mount();
  await user.click(await queueRow(lead.name));
  const panel = review();
  expect(await panel.findByText("Mesclado")).toBeInTheDocument();
  expect(
    panel.getByRole("button", { name: "Desfazer mesclagem" }),
  ).toBeInTheDocument();
  expect(
    panel.queryByRole("button", { name: "Confirmar criação no CRM" }),
  ).not.toBeInTheDocument();
  expect(panel.getByRole("radio")).toBeDisabled();
});

test("creation stays unavailable when the connected CRM lacks the capability", async () => {
  const user = userEvent.setup();
  vi.mocked(listLeads).mockResolvedValue({
    items: [lead],
    next_cursor: null,
    can_create: false,
  });
  mount();
  await user.click(await queueRow(lead.name));
  const panel = review();
  expect(
    await panel.findByText(
      "O CRM conectado não oferece criação de lead. A ação está indisponível.",
    ),
  ).toBeInTheDocument();
  await user.type(panel.getByLabelText("Motivo da decisão"), "Tentativa");
  expect(
    panel.getByRole("button", { name: "Confirmar criação no CRM" }),
  ).toBeDisabled();
});
