import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { EChartsCoreOption } from "echarts/core";
import type { CommandCenterSummary } from "@/features/agents/contract";
import { CommandCenterPage } from "./CommandCenterPage";
import { CommandCenterError, commandCenter } from "./api";
import { fixture } from "./fixture";

const captured = vi.hoisted(() => new Map<string, EChartsCoreOption>());
vi.mock("./api", () => ({
  commandCenter: vi.fn(),
  CommandCenterError: class CommandCenterError extends Error {
    status: number;
    code: string;
    correlationId: string | null;
    constructor(
      status: number,
      code: string,
      message: string,
      correlationId: string | null = null,
    ) {
      super(message);
      this.status = status;
      this.code = code;
      this.correlationId = correlationId;
    }
  },
}));
vi.mock("@/charts/AresChart", () => ({
  AresChart: ({
    option,
    label,
  }: {
    option: EChartsCoreOption;
    label: string;
  }) => {
    captured.set(label, option);
    return <div aria-label={label} />;
  },
}));
vi.mock("@/charts/aresTheme", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/charts/aresTheme")>();
  return {
    ...actual,
    useThemeTokens: () => ({
      font: "test",
      ink: "#ffffff",
      ink2: "#cccccc",
      ink3: "#aaaaaa",
      well: "#101517",
      panel: "#1a2029",
      raisedHi: "#28323f",
      edge: "#3e4a59",
      edgeHi: "#536276",
      edgeDark: "#080c11",
      grid: "#ffffff12",
      brasa: "#e96943",
      ambar: "#d99022",
      jade: "#3f8f74",
      aco: "#7089a6",
      lilas: "#9a83b5",
      radius: 3,
      bevelLit: 0.19,
      bevelShade: 0.26,
      contour: 0.34,
      rampLit: 0.51,
      rampShade: 0.44,
      lift: 3,
      liftHover: 5,
    }),
  };
});

afterEach(() => {
  cleanup();
  captured.clear();
  localStorage.clear();
});
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(commandCenter).mockResolvedValue(structuredClone(fixture));
});

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CommandCenterPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const showView = async (name: RegExp) => {
  await userEvent.setup().click(await screen.findByRole("button", { name }));
};
const impactBlock = async () => {
  await showView(/^Resultados/);
  return within(await screen.findByRole("region", { name: "Impacto ARES" }));
};
const withData = (patch: (data: CommandCenterSummary) => void) => {
  const data = structuredClone(fixture);
  patch(data);
  vi.mocked(commandCenter).mockResolvedValue(data);
};

test("unproven incremental is never rendered as zero", async () => {
  mount();
  const impact = await impactBlock();
  expect(impact.getByText("Não comprovado")).toBeInTheDocument();
  expect(impact.queryByText(/(^|[^\d.])0,00/)).not.toBeInTheDocument();
  expect(
    impact.getByText("0 de 44 execuções com custo medido"),
  ).toBeInTheDocument();
  expect(impact.getByText("Não informado")).toBeInTheDocument();
  expect(
    impact.getByText("42 outcomes sem moeda, fora dos totais"),
  ).toBeInTheDocument();
  expect(impact.getByText("3 de 3 observações sintéticas")).toBeInTheDocument();
});

test("opens on priorities and separates analysis from audit history", async () => {
  mount();
  await screen.findByRole("region", { name: "Agora" });
  expect(screen.getByRole("button", { name: /^Prioridades/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(
    screen.queryByRole("region", { name: "Impacto ARES" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "Trilha recente" }),
  ).not.toBeInTheDocument();
  await showView(/^Resultados/);
  expect(
    screen.getByRole("region", { name: "Impacto ARES" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "Agora" }),
  ).not.toBeInTheDocument();
  await showView(/^Histórico e critérios/);
  expect(
    screen.getByRole("region", { name: "Trilha recente" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "Definições e limitações" }),
  ).toBeInTheDocument();
});

test("loading state follows the first view's layout", () => {
  vi.mocked(commandCenter).mockImplementation(() => new Promise(() => {}));
  const { container } = mount();
  expect(
    container.querySelector('[aria-label="Carregando Command Center"]'),
  ).toHaveAttribute("aria-busy", "true");
  expect(container.querySelectorAll(".cc-primary-stats > *")).toHaveLength(4);
  expect(container.querySelector(".cc-analysis-grid")).not.toBeInTheDocument();
});

test("value at risk keeps currencies apart and counts missing values", async () => {
  mount();
  const now = within(await screen.findByRole("region", { name: "Agora" }));
  expect(now.getByText("BRL 17.591.000,00")).toBeInTheDocument();
  expect(now.getByText(/180 negócios · 2 sem valor/)).toBeInTheDocument();
  expect(now.getByText("3 sem moeda, fora dos totais")).toBeInTheDocument();
  expect(
    now.getByText("177 de 180 abertas com prazo definido"),
  ).toBeInTheDocument();
});

test("queue row links, labels and per-row approval", async () => {
  mount();
  const table = within(
    await screen.findByRole("region", { name: /Fila prioritária/ }),
  );
  const row = within(table.getAllByRole("row")[1]);
  expect(row.getByRole("link", { name: "Integração M2" })).toHaveAttribute(
    "href",
    "/opportunities/50000000-0000-0000-0000-000000000005",
  );
  expect(row.getByText("Crítica")).toBeInTheDocument();
  expect(row.getByText("Valor não informado")).toBeInTheDocument();
  expect(row.getByText("Sem responsável")).toBeInTheDocument();
  expect(row.getByText(/Vence em/)).toBeInTheDocument();
  expect(row.getByRole("link", { name: "Aprovar" })).toHaveAttribute(
    "href",
    "/approvals",
  );
  expect(row.getByText(/Follow-up vencido · 5 sinais/)).toBeInTheDocument();
});

test("raw enum codes never reach the reader", async () => {
  mount();
  await screen.findByRole("region", { name: "Agora" });
  for (const raw of [
    "prioritized",
    "create_task",
    "ares_agent",
    "degraded",
    "approved",
    "succeeded",
    "critical",
  ])
    expect(screen.queryByText(raw)).not.toBeInTheDocument();
  await showView(/^Histórico e critérios/);
  expect(screen.getByText("Aprovada")).toBeInTheDocument();
  expect(screen.getAllByText("Criar tarefa").length).toBeGreaterThan(0);
  expect(screen.getByText("Agente ARES")).toBeInTheDocument();
  await showView(/^Resultados/);
  expect(screen.getAllByText("influenciado").length).toBeGreaterThan(0);
});

test("history shows five events before expanding and criteria stay available", async () => {
  withData((data) => {
    data.activity.items = Array.from({ length: 8 }, (_, index) => ({
      ...data.activity.items[index % data.activity.items.length],
      correlation_id: `correlation-${index}`,
    }));
  });
  mount();
  await showView(/^Histórico e critérios/);
  expect(
    document.querySelectorAll(".cc-activity .event-trail-item"),
  ).toHaveLength(5);
  expect(
    screen.queryByText("Fórmula sintética de critical."),
  ).not.toBeInTheDocument();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "Mostrar mais 3 eventos" }));
  expect(
    document.querySelectorAll(".cc-activity .event-trail-item"),
  ).toHaveLength(8);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "Ver critérios e fórmulas" }));
  expect(screen.getByText(/Fórmula sintética de critical/)).toBeInTheDocument();
});

test("notices reflect synthetic data and degraded sources with the right action", async () => {
  mount();
  expect(await screen.findByText("Dados sintéticos.")).toBeInTheDocument();
  expect(screen.getByText("Fonte degradada.")).toBeInTheDocument();
  expect(screen.getByText("fake-crm-http · Degradada")).toBeInTheDocument();
  expect(
    screen.getAllByRole("link", { name: "Corrigir conexão" })[0],
  ).toHaveAttribute("href", "/pipeline");
  cleanup();
  withData((data) => {
    data.coverage.synthetic_outcomes = 0;
    data.capabilities.fix_connection = false;
  });
  mount();
  await screen.findByText("Fonte degradada.");
  expect(screen.queryByText("Dados sintéticos.")).not.toBeInTheDocument();
  const disabled = screen.getAllByRole("button", {
    name: "Corrigir conexão",
  })[0];
  expect(disabled).toBeDisabled();
  expect(disabled).toHaveAttribute("title");
});

test("capabilities gate approve and assign with explanations", async () => {
  withData((data) => {
    data.capabilities.approve = false;
  });
  mount();
  await screen.findByRole("region", { name: "Agora" });
  for (const button of screen.getAllByRole("button", { name: "Aprovar" })) {
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute(
      "title",
      "Aprovar exige papel gestor ou admin.",
    );
  }
  expect(
    screen.queryByRole("link", { name: "Aprovar" }),
  ).not.toBeInTheDocument();
  const assign = screen.getByRole("button", { name: "Assumir" });
  expect(assign).toBeDisabled();
  expect(assign).toHaveAttribute(
    "title",
    expect.stringContaining("não há endpoint"),
  );
});

test("seller scope hides tenant-only surfaces", async () => {
  withData((data) => {
    data.scope = { mode: "own", role: "seller", owner_user_id: "u" };
    data.impact.ai_cost = null;
    data.coverage.ai_runs = null;
    data.coverage.ai_measured_runs = null;
  });
  mount();
  expect(
    await screen.findByText("Escopo: minhas oportunidades"),
  ).toBeInTheDocument();
  await showView(/^Resultados/);
  expect(
    screen.queryByRole("link", { name: "Abrir Impacto ARES" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText("Indisponível no escopo próprio"),
  ).toBeInTheDocument();
  cleanup();
  withData((data) => {
    data.scope = { mode: "tenant", role: "auditor", owner_user_id: null };
  });
  mount();
  expect(await screen.findByText(/Leitura de auditoria/)).toBeInTheDocument();
});

test("period change reloads with the new window and remembers it", async () => {
  const user = userEvent.setup();
  mount();
  await screen.findByRole("region", { name: "Agora" });
  await user.selectOptions(screen.getByLabelText("Período"), "90");
  expect(commandCenter).toHaveBeenLastCalledWith(90, expect.any(AbortSignal));
  expect(localStorage.getItem("ares-cc-days")).toBe("90");
});

test("errors show the correlation and retry; denial hides the blocks", async () => {
  const user = userEvent.setup();
  vi.mocked(commandCenter).mockRejectedValue(
    new CommandCenterError(
      503,
      "command_center_unavailable",
      "Falhou.",
      "abc-123",
    ),
  );
  mount();
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("abc-123");
  await user.click(screen.getByRole("button", { name: "Tentar novamente" }));
  expect(commandCenter).toHaveBeenCalledTimes(2);
  expect(captured.size).toBe(0);
  cleanup();
  vi.mocked(commandCenter).mockRejectedValue(
    new CommandCenterError(
      403,
      "access_denied",
      "Esta conta não tem acesso ao Command Center.",
    ),
  );
  mount();
  expect(
    await screen.findByText("Esta conta não tem acesso ao Command Center."),
  ).toBeInTheDocument();
  expect(screen.queryByRole("region")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Período")).toBeDisabled();
});

test("an empty tenant explains itself instead of rendering zeros as results", async () => {
  withData((data) => {
    data.now.queue = [];
    data.now.open_at_risk = 0;
    data.now.value_at_risk = [];
    data.now.approvals = {
      pending: 0,
      expiring_within_6h: 0,
      items_limit: 5,
      items: [],
    };
    data.now.failed_actions = { count: 0, items_limit: 5, items: [] };
    data.now.connections = { total: 1, degraded: 0, revoked: 0, items: [] };
    data.impact.amounts = [];
    data.activity.items = [];
    data.coverage.synthetic_outcomes = 0;
  });
  mount();
  expect(
    await screen.findByText(/Nenhuma oportunidade aberta neste escopo/),
  ).toBeInTheDocument();
  await showView(/^Resultados/);
  expect(
    screen.getByText(/Nenhum outcome observado no período/),
  ).toBeInTheDocument();
  await showView(/^Histórico e critérios/);
  expect(
    screen.getByText(/Nenhuma decisão, intervenção ou outcome no período/),
  ).toBeInTheDocument();
  await showView(/^Prioridades/);
  expect(screen.getByText(/Nenhuma aprovação pendente/)).toBeInTheDocument();
  expect(screen.queryByText(/(^|[^\d.])0,00/)).not.toBeInTheDocument();
});

test("definition buttons focus the matching definition and every label has one", async () => {
  const user = userEvent.setup();
  const { container } = mount();
  await screen.findByRole("region", { name: "Agora" });
  const keys = new Set(fixture.definitions.map((item) => item.key));
  const visibleKeys = [
    ...container.querySelectorAll<HTMLElement>("[data-def-key]"),
  ].map((element) => element.dataset.defKey);
  await showView(/^Resultados/);
  visibleKeys.push(
    ...[...container.querySelectorAll<HTMLElement>("[data-def-key]")].map(
      (element) => element.dataset.defKey,
    ),
  );
  await showView(/^Prioridades/);
  await user.click(
    screen.getByRole("button", { name: "Definição de Críticas" }),
  );
  await waitFor(() => expect(document.activeElement?.id).toBe("def-critical"));
  expect(
    screen
      .getAllByText((_, node) =>
        (node?.textContent ?? "").includes("Fórmula sintética de critical."),
      )
      .filter((node) => node.tagName === "LI"),
  ).toHaveLength(1);
  expect(visibleKeys.length).toBeGreaterThan(10);
  for (const key of visibleKeys) expect(keys.has(key ?? "")).toBe(true);
});

test("charts receive honest series and a table alternative exists", async () => {
  mount();
  await showView(/^Resultados/);
  await screen.findByLabelText(
    "Abertas, trabalhadas, executadas e falhas por dia",
  );
  const trend = captured.get(
    "Abertas, trabalhadas, executadas e falhas por dia",
  ) as {
    series: Array<{ id: string; lineStyle?: { type?: string | number[] } }>;
  };
  expect(trend.series.map((entry) => entry.id)).toEqual([
    "opened",
    "worked",
    "executed",
    "failed",
  ]);
  const stacked = captured.get(
    "Sinais detectados por dia, empilhados por tipo",
  ) as {
    series: Array<{ id: string; stack: string; data: Array<number | null> }>;
    legend: { data: string[] };
  };
  expect(stacked.series.every((entry) => entry.stack === "signals")).toBe(true);
  expect(stacked.series.map((entry) => entry.id)).toEqual([
    "follow_up_overdue",
    "missing_next_step",
  ]);
  expect(stacked.series[0].data).toEqual([0, 4, 0, 0]);
  expect(stacked.legend.data).toEqual([
    "Follow-up vencido (sev. 5)",
    "Próximo passo ausente (sev. 3)",
  ]);
  const funnel = captured.get(
    "Oportunidades da coorte que alcançaram cada estado",
  ) as {
    series: Array<{ data: Array<{ name: string }> }>;
  };
  expect(funnel.series[0].data.map((row) => row.name)).toEqual([
    "Detectadas",
    "Priorizadas",
    "Aguardando decisão",
    "Autorizadas",
    "Em execução",
    "Em observação",
    "Encerradas",
  ]);
  const user = userEvent.setup();
  const signalsFrame = screen.getByRole("region", { name: "Sinais por tipo" });
  await user.click(
    within(signalsFrame).getByRole("button", { name: /Tabela/ }),
  );
  const table = within(signalsFrame).getByRole("table");
  expect(
    within(table).getByRole("columnheader", {
      name: "Follow-up vencido (sev. 5)",
    }),
  ).toBeInTheDocument();
  expect(
    within(table).getByRole("columnheader", { name: "Total" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/1 sinal\(is\) sem oportunidade vinculada/),
  ).toBeInTheDocument();
});
