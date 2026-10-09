import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  getOpportunityContext,
  getSpecialistAnalysis,
  startSpecialistAnalysis,
} from "./api";
import { SpecialistAnalysisPanel } from "./specialist-analysis-panel";
import type { SpecialistAnalysis } from "./types";

vi.mock("./api", () => ({
  getOpportunityContext: vi.fn(),
  getSpecialistAnalysis: vi.fn(),
  startSpecialistAnalysis: vi.fn(),
}));
const base: SpecialistAnalysis = {
  enabled: true,
  can_request: true,
  state: "not_requested",
  triage: null,
  diagnosis: null,
  workflow_id: null,
  valid_until: null,
  source: "Contexto sintético",
};
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <SpecialistAnalysisPanel opportunityId="synthetic-opportunity" />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSpecialistAnalysis).mockResolvedValue(base);
});
afterEach(cleanup);

test("preserves the same intent after an uncertain request failure", async () => {
  const user = userEvent.setup();
  vi.mocked(getOpportunityContext).mockResolvedValue({
    context_ref: "synthetic-context",
  } as Awaited<ReturnType<typeof getOpportunityContext>>);
  vi.mocked(startSpecialistAnalysis)
    .mockRejectedValueOnce(new Error("service_unavailable"))
    .mockResolvedValueOnce({ id: "workflow", status: "queued" });
  mount();
  await user.click(
    await screen.findByRole("button", { name: "Analisar evidências" }),
  );
  await user.click(
    await screen.findByRole("button", { name: "Repetir solicitação" }),
  );
  await waitFor(() => expect(startSpecialistAnalysis).toHaveBeenCalledTimes(2));
  expect(vi.mocked(startSpecialistAnalysis).mock.calls[0][0]).toEqual(
    vi.mocked(startSpecialistAnalysis).mock.calls[1][0],
  );
  expect(getOpportunityContext).toHaveBeenCalledTimes(1);
});

test("distinguishes grounded facts from hypotheses and keeps zeros visible", async () => {
  vi.mocked(getSpecialistAnalysis).mockResolvedValue({
    ...base,
    state: "ready",
    triage: {
      summary: "Análise de evidência sintética",
      category: "data_gap",
      proposed_urgency: "high",
      evidence_refs: [],
      limitations: [],
    },
    diagnosis: {
      summary: "Há lacunas a revisar",
      facts: [{ path: "/deal/value", value: "0" }],
      hypotheses: [
        {
          explanation: "Contato pode ter ocorrido fora do CRM",
          supporting_refs: [],
          contrary_refs: [],
          missing_information: ["Confirmar com o vendedor"],
        },
      ],
      limitations: [],
      needs_human_review: true,
    },
  });
  mount();
  expect(await screen.findByText("Fatos conferidos no contexto")).toBeVisible();
  expect(screen.getByText("0")).toBeVisible();
  expect(screen.getByText("Hipóteses — precisam de confirmação")).toBeVisible();
  expect(screen.getByText("Urgência proposta: Alta")).toBeVisible();
});

test("does not offer analysis when the server denies capability", async () => {
  vi.mocked(getSpecialistAnalysis).mockResolvedValue({
    ...base,
    can_request: false,
    enabled: false,
    state: "disabled",
  });
  mount();
  expect(
    await screen.findByText(
      "Análise especializada desativada para esta empresa.",
    ),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Analisar evidências" }),
  ).not.toBeInTheDocument();
});
