import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { NotificationBell } from "./NotificationBell";
import {
  getNotifications,
  markNotification,
  type NotificationPage,
} from "./api";
vi.mock("./api", () => ({
  getNotifications: vi.fn(),
  markNotification: vi.fn(),
}));
const page: NotificationPage = {
  items: [
    {
      id: "finding-1",
      opportunity_id: "opp-1",
      rule_title: "Propostas paradas",
      title: "Negócio sintético",
      revision: 2,
      status: "updated",
      severity: "high",
      summary: "Condição detectada",
      interpretation_status: "degraded",
      interpretation_json: null,
      detected_at: "2026-10-08T12:00:00Z",
      updated_at: "2026-10-08T13:00:00Z",
      is_read: false,
      is_archived: false,
    },
  ],
  unread_count: 24,
  total: 24,
  next_offset: 10,
  source: "Teste",
};
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getNotifications).mockResolvedValue(page);
  vi.mocked(markNotification).mockResolvedValue({});
});
afterEach(cleanup);
test("badge uses full unread count and supports personal read/archive", async () => {
  const user = userEvent.setup();
  mount();
  await screen.findByRole("button", { name: "Notificações: 24 não lidas" });
  await user.click(
    screen.getByRole("button", { name: "Notificações: 24 não lidas" }),
  );
  expect(
    screen.getByText(
      "Interpretação indisponível; evidência objetiva preservada.",
    ),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Marcar lida" }));
  await waitFor(() =>
    expect(markNotification).toHaveBeenCalledWith("finding-1", 2, "read"),
  );
  await user.click(screen.getByRole("button", { name: "Arquivar" }));
  await waitFor(() =>
    expect(markNotification).toHaveBeenCalledWith("finding-1", 2, "archive"),
  );
  expect(
    screen.getByText(/Ler ou arquivar não resolve o risco/),
  ).toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(
    screen.getByRole("button", { name: "Notificações: 24 não lidas" }),
  ).toHaveFocus();
});
test("pagination and archive filter query separate scoped pages", async () => {
  const user = userEvent.setup();
  mount();
  await user.click(
    await screen.findByRole("button", { name: "Notificações: 24 não lidas" }),
  );
  await user.click(screen.getByRole("button", { name: "Próximas" }));
  await waitFor(() => expect(getNotifications).toHaveBeenCalledWith(10, "all"));
  await user.selectOptions(screen.getByLabelText("Exibir"), "archived");
  await waitFor(() =>
    expect(getNotifications).toHaveBeenCalledWith(0, "archived"),
  );
});
test("unavailable inbox offers refresh and exposes no findings", async () => {
  vi.mocked(getNotifications).mockRejectedValue(
    new Error("synthetic unavailable"),
  );
  const user = userEvent.setup();
  mount();
  await user.click(
    await screen.findByRole("button", { name: "Notificações: indisponíveis" }),
  );
  await screen.findByRole("alert");
  expect(screen.queryByText("Negócio sintético")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Atualizar notificações" }),
  ).toBeEnabled();
});
