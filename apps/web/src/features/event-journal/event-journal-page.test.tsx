import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { EventJournalPage } from "./event-journal-page";

vi.mock("./event-activity-chart", () => ({
  EventActivityChart: ({ partialMessage }: { partialMessage?: string }) => (
    <p>{partialMessage}</p>
  ),
}));

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({
        data: { session: { access_token: "test-access-token" } },
      }),
    },
  },
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("shows a meaningful empty state without inventing metrics", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        items: [],
        total: 0,
        source: "FakeCRM local",
        freshness_at: "2026-08-29T03:00:00Z",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={client}>
      <EventJournalPage />
    </QueryClientProvider>,
  );

  expect(await screen.findByText("Journal vazio")).toBeInTheDocument();
  expect(screen.queryByText(/Nenhum dado fictício/)).not.toBeInTheDocument();
});

test("navigates bounded journal pages and returns to the newest events", async () => {
  const event = (id: string) => ({
    id,
    provider_event_id: id,
    event_type: "deal.updated",
    aggregate_id: id,
    aggregate_type: "deal",
    correlation_id: "synthetic-correlation",
    source: "crm",
    producer: "synthetic",
    status: "recorded",
    recorded_at: "2026-10-07T12:00:00Z",
    occurred_at: "2026-10-07T12:00:00Z",
    data: {},
  });
  const requests: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    requests.push(url);
    const second = url.includes("cursor=older");
    return new Response(
      JSON.stringify({
        items: [event(second ? "older-event" : "newest-event")],
        total: 2,
        next_cursor: second ? null : "older",
        source: "Synthetic journal",
        freshness_at: "2026-10-07T12:00:00Z",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <EventJournalPage />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  expect(await screen.findByText("newest-event")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Próxima página" }),
    ).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "Próxima página" }));
  expect(await screen.findByText("older-event")).toBeInTheDocument();
  expect(screen.queryByText("newest-event")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Próxima página" })).toBeDisabled();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Anterior" })).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "Anterior" }));
  expect(await screen.findByText("newest-event")).toBeInTheDocument();
  expect(requests.every((url) => url.includes("limit=50"))).toBe(true);
  expect(requests.some((url) => url.includes("cursor=older"))).toBe(true);
});
