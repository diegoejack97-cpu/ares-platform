import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { LicensePage as LicenseData } from "@/features/agents/contract";
import { LicensePage, QuotaNotice } from "./LicensePage";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({
        data: { session: { access_token: "synthetic" } },
      }),
    },
  },
}));

const licenses: LicenseData = {
  seats_limit: 3,
  used: 2,
  invitations: [
    {
      id: "10000000-0000-0000-0000-000000000001",
      email: "convidado@example.invalid",
      role: "seller",
      status: "pending",
      version: 1,
    },
    {
      id: "10000000-0000-0000-0000-000000000009",
      email: "antigo@example.invalid",
      role: "manager",
      status: "cancelled",
      version: 2,
    },
  ],
  memberships: [
    {
      user_id: "20000000-0000-0000-0000-000000000002",
      email: "admin@example.invalid",
      role: "admin",
      active: true,
      version: 1,
    },
  ],
  next_invitation: null,
  next_member: null,
};

type Call = { path: string; init?: RequestInit };
const calls: Call[] = [];
function serve(
  handlers: Record<
    string,
    (init?: RequestInit) => { status?: number; body: unknown }
  >,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = new URL(url).pathname.replace("/api/v1/account", "");
      calls.push({ path, init });
      const handler = handlers[path] ?? handlers["*"];
      const result = handler(init);
      return new Response(JSON.stringify(result.body), {
        status: result.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  calls.length = 0;
});
beforeEach(() => vi.resetAllMocks());

function mount(element = <LicensePage />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>,
  );
}
const row = (text: string) =>
  within(screen.getByRole("row", { name: new RegExp(text) }));

test("invite registers a reason and never sends e-mail; pending seats count as used", async () => {
  const user = userEvent.setup();
  serve({
    "/licenses": () => ({ body: licenses }),
    "/invitations": () => ({ body: { id: "new", version: 1 } }),
  });
  mount();
  expect(
    await screen.findByText("2 de 3 licenças ocupadas ou reservadas."),
  ).toBeInTheDocument();
  expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "2");
  expect(screen.getByText("1 disponível")).toBeInTheDocument();
  expect(screen.getByText(/O registro não envia e-mail/)).toBeInTheDocument();
  await user.type(screen.getByLabelText("E-mail"), "nova@example.invalid");
  await user.selectOptions(screen.getByLabelText("Papel"), "manager");
  await user.type(
    screen.getByLabelText("Justificativa do convite"),
    "Onboarding",
  );
  await user.click(screen.getByRole("button", { name: "Registrar convite" }));
  expect(
    await screen.findByText("Alteração registrada e auditada."),
  ).toBeInTheDocument();
  const invite = calls.find((call) => call.path === "/invitations");
  expect(invite?.init?.method).toBe("POST");
  expect(JSON.parse(String(invite?.init?.body))).toEqual({
    email: "nova@example.invalid",
    role: "manager",
    reason: "Onboarding",
  });
});

test("a full contract disables new invitations and explains why", async () => {
  serve({ "/licenses": () => ({ body: { ...licenses, used: 3 } }) });
  mount();
  await screen.findByText("3 de 3 licenças ocupadas ou reservadas.");
  expect(
    screen.getByRole("button", { name: "Registrar convite" }),
  ).toBeDisabled();
  expect(screen.getByText(/Contrato lotado/)).toBeInTheDocument();
});

test("rows translate roles and states, and only pending invitations offer actions", async () => {
  serve({ "/licenses": () => ({ body: licenses }) });
  mount();
  await screen.findByText("2 de 3 licenças ocupadas ou reservadas.");
  const pending = row("convidado@example.invalid");
  expect(pending.getByText("Vendedor")).toBeInTheDocument();
  expect(pending.getByText("Pendente")).toBeInTheDocument();
  expect(pending.getByRole("button", { name: /^Ativar/ })).toBeInTheDocument();
  const cancelled = row("antigo@example.invalid");
  expect(cancelled.getByText("Gestor")).toBeInTheDocument();
  expect(cancelled.getByText("Cancelado")).toBeInTheDocument();
  expect(cancelled.queryByRole("button")).not.toBeInTheDocument();
  const member = row("admin@example.invalid");
  expect(member.getByText("Administrador")).toBeInTheDocument();
  expect(member.getByText("Ativo")).toBeInTheDocument();
  expect(
    member.getByRole("button", { name: "Desativar admin@example.invalid" }),
  ).toBeInTheDocument();
});

test("cancel and activation open an inline form that requires a reason", async () => {
  const user = userEvent.setup();
  serve({
    "/licenses": () => ({ body: licenses }),
    "*": () => ({ body: { cancelled: true } }),
  });
  mount();
  await screen.findByText("2 de 3 licenças ocupadas ou reservadas.");
  await user.click(
    screen.getByRole("button", { name: "Ativar convidado@example.invalid" }),
  );
  const activate = screen.getByRole("button", { name: "Confirmar ativação" });
  expect(activate).toBeDisabled();
  await user.type(
    screen.getByLabelText("Justificativa da alteração"),
    "Conta verificada",
  );
  expect(activate).toBeDisabled();
  await user.type(
    screen.getByLabelText("ID da conta verificada para ativação"),
    "3f1c2a4e-9b7d-4c1e-8a2b-5d6e7f8a9b0c",
  );
  expect(activate).toBeEnabled();
  await user.click(
    screen.getByRole("button", { name: "Cancelar convidado@example.invalid" }),
  );
  expect(
    screen.queryByLabelText("ID da conta verificada para ativação"),
  ).not.toBeInTheDocument();
  const cancel = screen.getByRole("button", { name: "Confirmar cancelamento" });
  expect(cancel).toBeDisabled();
  await user.type(
    screen.getByLabelText("Justificativa da alteração"),
    "Duplicado",
  );
  await user.click(cancel);
  await screen.findByText("Alteração registrada e auditada.");
  const request = calls.find((call) => call.path.endsWith("/cancel"));
  expect(request?.path).toBe(
    `/invitations/${licenses.invitations[0].id}/cancel`,
  );
  expect(JSON.parse(String(request?.init?.body))).toEqual({
    expected_version: 1,
    active: false,
    reason: "Duplicado",
  });
}, 15_000);

test("server refusals surface a readable message with the correlation", async () => {
  serve({
    "/licenses": () => ({
      status: 409,
      body: {
        detail: {
          code: "seat_contract_unconfigured",
          correlation_id: "abc-123",
        },
      },
    }),
  });
  mount();
  expect(
    await screen.findByText(
      "Operação não concluída: seat_contract_unconfigured. Correlação: abc-123.",
    ),
  ).toBeInTheDocument();
  cleanup();
  serve({
    "/licenses": () => ({
      status: 403,
      body: { detail: { code: "admin_required" } },
    }),
  });
  mount();
  expect(
    await screen.findByText(
      "Somente administradores do tenant acessam esta área.",
    ),
  ).toBeInTheDocument();
});

test("quota notice distinguishes a zero budget from an 80% warning", async () => {
  serve({
    "/quota": () => ({
      body: {
        configured: true,
        warning: true,
        daily: "0",
        monthly: "0",
        ai_daily_budget_brl: "0.000000",
        ai_monthly_budget_brl: "0.000000",
      },
    }),
  });
  mount(<QuotaNotice />);
  expect(
    await screen.findByText(/Cota de IA zerada pelo provedor/),
  ).toBeInTheDocument();
  cleanup();
  serve({
    "/quota": () => ({
      body: {
        configured: true,
        warning: true,
        daily: "8.50",
        monthly: "40.00",
        ai_daily_budget_brl: "10.000000",
        ai_monthly_budget_brl: "100.000000",
      },
    }),
  });
  mount(<QuotaNotice />);
  expect(
    await screen.findByText(/atingiram pelo menos 80% do contrato/),
  ).toBeInTheDocument();
  expect(screen.getByText(/R\$\s8,50 hoje/)).toBeInTheDocument();
  cleanup();
  serve({ "/quota": () => ({ body: { configured: false } }) });
  mount(<QuotaNotice />);
  expect(
    await screen.findByText(/Cota de IA não configurada/),
  ).toBeInTheDocument();
});
