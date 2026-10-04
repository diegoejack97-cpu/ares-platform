import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { getPipeline, movePipelineDeal, PipelineError } from "./api";
import { formatPipelineValue, PipelinePage } from "./PipelinePage";
import type { PipelineSnapshot } from "./types";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  getPipeline: vi.fn(),
  movePipelineDeal: vi.fn(),
}));

const snapshot: PipelineSnapshot = {
  items: [
    {
      id: "canonical-1",
      external_id: "deal-001",
      title: "Proposta Serra",
      stage: "proposal",
      value: null,
      currency: null,
      version: 4,
      owner_id: null,
      changed_at: null,
      synthetic: true,
      is_missing: false,
    },
  ],
  stages: [
    { id: "proposal", label: "Proposta" },
    { id: "won", label: "Ganho" },
  ],
  capabilities: { update_stage: true, read_deals: true },
  permissions: { can_move: true, can_manage: false },
  freshness_at: "2026-09-10T00:00:00Z",
  source: "FakeCRM HTTP",
  partial: false,
  missing_count: 0,
  next_cursor: null,
  connection: {
    id: "connection-1",
    provider: "fake-crm-http",
    status: "healthy",
  },
};

afterEach(cleanup);

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getPipeline).mockResolvedValue(structuredClone(snapshot));
});
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PipelinePage />
    </QueryClientProvider>,
  );
}

test("preserva valor ausente, fonte e responsabilidade sem receita inventada", async () => {
  renderPage();
  expect(await screen.findByText("Proposta Serra")).toBeInTheDocument();
  expect(screen.getByText("Valor não informado")).toBeInTheDocument();
  expect(screen.getByText("Dado sintético · FakeCRM")).toBeInTheDocument();
  expect(
    screen.getByText(/Comando humano não é intervenção de IA/),
  ).toBeInTheDocument();
  expect(formatPipelineValue(0, "BRL")).toMatch(/0,00/);
  expect(formatPipelineValue(500, null)).toContain("moeda não informada");
});

test("não move antes de confirmação humana e externa", async () => {
  const user = userEvent.setup();
  let confirm: (result: {
    status: string;
    correlation_id: string;
  }) => void = () => {};
  vi.mocked(movePipelineDeal).mockImplementation(
    () =>
      new Promise((resolve) => {
        confirm = resolve;
      }),
  );
  renderPage();
  await user.selectOptions(
    await screen.findByLabelText("Mover Proposta Serra para"),
    "won",
  );
  expect(movePipelineDeal).not.toHaveBeenCalled();
  await user.click(
    screen.getByRole("button", { name: "Confirmar e executar" }),
  );
  expect(
    within(
      document.querySelector('[aria-label="Etapa Proposta"]') as HTMLElement,
    ).getByText("Proposta Serra"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Aguardando confirmação…" }),
  ).toBeDisabled();
  expect(movePipelineDeal).toHaveBeenCalledWith(
    "canonical-1",
    expect.objectContaining({
      stage: "won",
      expected_version: 4,
      confirmed: true,
      idempotency_key: expect.any(String),
    }),
  );
  confirm({ status: "succeeded", correlation_id: "trace-123" });
  expect(
    await screen.findByText(/Mudança confirmada pelo CRM/),
  ).toHaveTextContent("trace-123");
});

test("Cancelar fecha uma proposta ainda não enviada sem chamar o CRM", async () => {
  const user = userEvent.setup();
  renderPage();
  await user.selectOptions(
    await screen.findByLabelText("Mover Proposta Serra para"),
    "won",
  );
  await user.click(screen.getByRole("button", { name: "Cancelar" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(movePipelineDeal).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Mover Proposta Serra para")).toBeEnabled();
});

test("conflito exige nova leitura e não repete automaticamente o comando", async () => {
  const user = userEvent.setup();
  vi.mocked(movePipelineDeal).mockRejectedValue(
    new PipelineError(
      "Versão divergente",
      409,
      "version_conflict",
      "trace-conflict",
    ),
  );
  renderPage();
  await user.selectOptions(
    await screen.findByLabelText("Mover Proposta Serra para"),
    "won",
  );
  await user.click(
    screen.getByRole("button", { name: "Confirmar e executar" }),
  );
  expect(
    await screen.findByText(/Conflito de versão ou intento/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Confirmar e executar" }),
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Recarregar estado e revisar" }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(movePipelineDeal).toHaveBeenCalledTimes(1);
});

test("resultado incerto reutiliza exatamente a mesma chave por intento", async () => {
  const user = userEvent.setup();
  vi.mocked(movePipelineDeal)
    .mockRejectedValueOnce(
      new PipelineError("Timeout", 504, "provider_timeout"),
    )
    .mockResolvedValueOnce({ status: "succeeded", duplicate: true });
  renderPage();
  await user.selectOptions(
    await screen.findByLabelText("Mover Proposta Serra para"),
    "won",
  );
  await user.click(
    screen.getByRole("button", { name: "Confirmar e executar" }),
  );
  await user.click(
    await screen.findByRole("button", { name: "Fechar janela" }),
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    screen.getByText("Mudança ainda não confirmada pelo CRM"),
  ).toBeInTheDocument();
  expect(
    screen.queryByLabelText("Mover Proposta Serra para"),
  ).not.toBeInTheDocument();
  expect(movePipelineDeal).toHaveBeenCalledTimes(1);
  await user.click(
    screen.getByRole("button", { name: "Consultar intento pendente" }),
  );
  await user.click(
    await screen.findByRole("button", { name: "Consultar o mesmo intento" }),
  );
  await waitFor(() => expect(movePipelineDeal).toHaveBeenCalledTimes(2));
  expect(vi.mocked(movePipelineDeal).mock.calls[0]).toEqual(
    vi.mocked(movePipelineDeal).mock.calls[1],
  );
  expect(await screen.findByText(/nenhuma duplicação/)).toBeInTheDocument();
  expect(screen.getByLabelText("Mover Proposta Serra para")).toBeEnabled();
});

test("papel somente leitura e capability ausente escondem escrita antes da interação", async () => {
  vi.mocked(getPipeline).mockResolvedValue({
    ...snapshot,
    permissions: { can_move: false, can_manage: false },
    capabilities: { read_deals: true, update_stage: false },
  });
  renderPage();
  expect(
    await screen.findByText(/Provedor sem capacidade/),
  ).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Arrastar/ }),
  ).not.toBeInTheDocument();
});

test("erro de leitura oferece tentativa sem substituir o erro por dados fictícios", async () => {
  vi.mocked(getPipeline).mockRejectedValue(new Error("API indisponível"));
  renderPage();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API indisponível",
  );
  expect(
    screen.getByRole("button", { name: "Tentar novamente" }),
  ).toBeEnabled();
  expect(screen.queryByText("Proposta Serra")).not.toBeInTheDocument();
});
