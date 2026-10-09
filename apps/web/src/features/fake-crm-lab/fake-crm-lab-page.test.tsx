import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import {
  createFakeCRMTask,
  getFakeCRMLabSnapshot,
  testFakeCRMFault,
} from "./api";
import { FakeCRMLabPage } from "./fake-crm-lab-page";
import type { FakeCRMLabSnapshot } from "./types";

vi.mock("./api", () => ({
  addFakeCRMNote: vi.fn(),
  createFakeCRMTask: vi.fn(),
  getFakeCRMLabSnapshot: vi.fn(),
  resetFakeCRMLab: vi.fn(),
  sendFakeCRMEvent: vi.fn(),
  testFakeCRMFault: vi.fn(),
  updateFakeCRMStage: vi.fn(),
}));

const snapshot = {
  health: { status: "ok", service: "fake-crm-sandbox", synthetic: true },
  capabilities: {
    read_deals: true,
    describe_schema: true,
    read_changes: true,
    create_task: true,
    add_note: true,
    update_stage: true,
    signed_webhooks: true,
  },
  stages: [
    { id: "qualification", label: "Qualification" },
    { id: "proposal", label: "Proposal" },
  ],
  deals: [
    {
      id: "deal-001",
      title: "Oportunidade Sintética 001",
      stage: "qualification",
      value: 17750,
      currency: "BRL",
      version: 1,
      changed_at: "2026-09-01T12:00:00Z",
      owner_id: "seller-01",
      company_id: "company-001",
      contact_id: "contact-001",
      synthetic: true,
      scenario: "follow_up_overdue",
    },
  ],
  counts: {
    companies: 20,
    contacts: 40,
    deals: 60,
    activities: 60,
    tasks: 0,
    notes: 0,
  },
  watermark: "2026-09-01T12:00:00Z",
  freshness_at: "2026-09-03T12:00:00Z",
  source: "FakeCRM HTTP Sandbox",
  docs_url: "http://127.0.0.1:8011/docs",
} satisfies FakeCRMLabSnapshot;

beforeEach(() => {
  vi.mocked(getFakeCRMLabSnapshot).mockResolvedValue(snapshot);
  vi.mocked(createFakeCRMTask).mockResolvedValue({
    external_id: "task-0001",
    duplicate: false,
  });
  vi.mocked(testFakeCRMFault).mockResolvedValue({
    scenario: "rate_limit",
    observed: true,
    status_code: 429,
    code: "simulated_rate_limit",
    retry_after: "1",
  });
});

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <FakeCRMLabPage />
    </QueryClientProvider>,
  );
}

test("renders synthetic provenance, pipeline, and operational controls", async () => {
  renderPage();

  expect(
    await screen.findAllByText("Oportunidade Sintética 001"),
  ).not.toHaveLength(0);
  expect(
    screen.getByText(/Não é o CRM oficial do cliente/i),
  ).toBeInTheDocument();
  expect(screen.getByText(/não são receita real/i)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /Enviar evento ao ARES/i }),
  ).toBeEnabled();
  expect(
    screen.getByRole("link", { name: /Abrir contrato HTTP/i }),
  ).toHaveAttribute("href", "http://127.0.0.1:8011/docs");
});

test("executes a task and reports the operation without exposing credentials", async () => {
  const user = userEvent.setup();
  renderPage();

  await screen.findAllByText("Oportunidade Sintética 001");
  await user.click(screen.getByRole("button", { name: "Criar" }));

  expect(createFakeCRMTask).toHaveBeenCalledWith(
    "deal-001",
    "Retomar oportunidade sintética",
  );
  expect(
    await screen.findByText("Tarefa criada no sandbox"),
  ).toBeInTheDocument();
  expect(screen.queryByText(/local-sandbox-key/i)).not.toBeInTheDocument();
});
