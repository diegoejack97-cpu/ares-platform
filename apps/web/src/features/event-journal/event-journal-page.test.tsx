import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { EventJournalPage } from "./event-journal-page";

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
