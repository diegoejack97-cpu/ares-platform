import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ChatPage } from "./ChatPage";
import { getChat, openFindingChat, sendChat, saveChatFeedback } from "./api";
import type { ChatHistory } from "@/features/agents/contract";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  getChat: vi.fn(),
  openFindingChat: vi.fn(),
  sendChat: vi.fn(),
  saveChatFeedback: vi.fn(),
}));
vi.mock("@/features/auth/auth-context", () => ({
  useAuth: () => ({
    session: {
      user: {
        id: "synthetic-user",
        app_metadata: { active_tenant_id: "synthetic-tenant" },
      },
    },
  }),
}));
vi.mock("@/features/opportunities/api", () => ({
  getSpecialistAnalysis: vi.fn().mockResolvedValue({ enabled: false }),
  getOpportunityContext: vi.fn(),
  startSpecialistAnalysis: vi.fn(),
}));
const context = {
  context_ref: "context",
  content: "{}",
  content_hash: "hash",
  tokens_upper_bound: 2,
  token_limit: 2500,
  count_method: "utf8",
  citations: [],
  truncated: false,
  captured_at: "2026-10-08T12:00:00Z",
  source: "Synthetic",
};
const history: ChatHistory = {
  items: [
    {
      id: "message",
      user_text: "Explique esta notificação.",
      assistant_text: "Condição detectada com dados atuais.",
      status: "succeeded",
      context_json: context,
      tool_calls_json: [],
      created_at: "2026-10-08T12:00:00Z",
    },
  ],
  context,
  model_available: false,
  next_before: null,
  finding: {
    finding_id: "finding",
    opportunity_id: "opportunity",
    revision: 1,
    title: "Negócio sintético",
    rule_title: "SLA vencido",
    detected_at: "2026-10-08T12:00:00Z",
    status: "open",
    condition_current: true,
    changed: false,
    summary: "SLA detectado",
    source: "Synthetic",
    suggestions: ["O que mudou?"],
  },
};
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/chat?finding=finding"]}>
        <ChatPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getChat).mockResolvedValue(history);
  vi.mocked(openFindingChat).mockResolvedValue({});
  vi.mocked(saveChatFeedback).mockResolvedValue({});
  Element.prototype.scrollTo = vi.fn();
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
test("finding opens once and keeps origin and return navigation", async () => {
  const user = userEvent.setup();
  mount();
  await screen.findByText("Negócio sintético");
  expect(openFindingChat).toHaveBeenCalledTimes(1);
  expect(getChat).toHaveBeenCalledWith(
    undefined,
    expect.any(AbortSignal),
    "finding",
  );
  expect(
    screen.getByRole("link", { name: "Ver oportunidade e análises" }),
  ).toHaveAttribute("href", "/opportunities/opportunity");
  await user.click(screen.getByRole("button", { name: "Atualizar conversa" }));
  await waitFor(() => expect(getChat).toHaveBeenCalledTimes(2));
  expect(openFindingChat).toHaveBeenCalledTimes(1);
});
test("feedback carries only owned message, rating and reason", async () => {
  const user = userEvent.setup();
  mount();
  await user.click(await screen.findByRole("button", { name: "Não útil" }));
  await user.type(
    screen.getByLabelText("Motivo do feedback"),
    "Faltou explicar a origem",
  );
  await user.click(screen.getByRole("button", { name: "Enviar feedback" }));
  await waitFor(() =>
    expect(saveChatFeedback).toHaveBeenCalledWith(
      "message",
      "unhelpful",
      "Faltou explicar a origem",
    ),
  );
});
test("Enter sends finding reference and removes text from composer", async () => {
  const user = userEvent.setup();
  mount();
  await screen.findByText("Negócio sintético");
  vi.mocked(sendChat).mockImplementation(
    async (_scope, _text, _signal, receive) => {
      receive("context", { ...context, message_id: "reply" });
      receive("token", { text: "Dados consultados novamente." });
      receive("done", { message_id: "reply" });
    },
  );
  const composer = screen.getByRole("textbox", {
    name: /Pergunte ao ARES|Sua pergunta/i,
  });
  await user.type(composer, "O que mudou?{Enter}");
  await waitFor(() =>
    expect(sendChat).toHaveBeenCalledWith(
      undefined,
      "O que mudou?",
      expect.any(AbortSignal),
      expect.any(Function),
      "finding",
    ),
  );
  expect(composer).toHaveValue("");
});

vi.mock("./chat-recommendation-action", () => ({ChatRecommendationAction: () => null}));
