import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import type { Recommendation } from "@/features/opportunities/types";

import { RecommendationCard } from "./recommendation-card";

const recommendation: Recommendation = {
  id: "rec-1",
  intervention_id: "int-1",
  opportunity_id: "op-1",
  correlation_id: "corr-1",
  recommended_action: {
    action_kind: "create_task",
    payload: { title: "Retomar contato" },
  },
  rationale: "Sinais determinísticos indicam risco comercial.",
  confidence: 0.91,
  alternatives: [
    {
      label: "Registrar nota",
      action: { action_kind: "add_note", payload: { body: "Revisar" } },
      tradeoff: "Não cria compromisso com prazo.",
    },
  ],
  contraindication: "Não executar se o cliente já respondeu.",
  urgency: "critical",
  generation_mode: "deterministic_fallback",
  status: "pending",
  version: 1,
  context_ref: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  policy_verdict: "require_approval",
  policy_set: "ares-connect-actions",
  policy_version: 1,
  policy_hash: "hash",
  approval_id: "approval-1",
  approval_status: "pending",
  approval_expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  can_decide: true,
  approval_required_role: "manager",
  intent_id: null,
  action_status: null,
  executed_action: null,
  execution_result: null,
};

afterEach(cleanup);

test("keeps recommendation, policy, human decision and execution visibly separate", async () => {
  const user = userEvent.setup();
  const onDecide = vi.fn();
  render(
    <RecommendationCard recommendation={recommendation} onDecide={onDecide} />,
  );

  expect(screen.getByText("Ação recomendada")).toBeInTheDocument();
  expect(screen.getByText("require_approval")).toBeInTheDocument();
  expect(screen.getByText("não autorizada")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /editar antes/i }));
  const input = screen.getByLabelText("Conteúdo que será executado");
  await user.clear(input);
  await user.type(input, "Retomar contato amanhã");
  await user.click(screen.getByRole("button", { name: /aprovar edição/i }));

  expect(onDecide).toHaveBeenCalledWith(
    expect.objectContaining({
      verdict: "edited",
      expected_version: 1,
      edited_payload: expect.objectContaining({
        payload: expect.objectContaining({ title: "Retomar contato amanhã" }),
      }),
    }),
  );
});

test.each([false, undefined])(
  "hides approval controls without server permission (%s)",
  async (permission) => {
    const onDecide = vi.fn();
    render(
      <RecommendationCard
        recommendation={{ ...recommendation, can_decide: permission }}
        onDecide={onDecide}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /^aprovar$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /editar antes/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /rejeitar/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/exige aprovação de um gestor/i),
    ).toBeInTheDocument();
    expect(onDecide).not.toHaveBeenCalled();
  },
);

test("does not allow an expired approval even with stale server permission", () => {
  render(
    <RecommendationCard
      recommendation={{
        ...recommendation,
        approval_expires_at: new Date(Date.now() - 1000).toISOString(),
      }}
      onDecide={vi.fn()}
    />,
  );
  expect(
    screen.queryByRole("button", { name: /^aprovar$/i }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/aprovação expirou/i)).toBeInTheDocument();
});

test("removes approval actions when the displayed approval expires", () => {
  vi.useFakeTimers();
  try {
    const now = Date.now();
    render(
      <RecommendationCard
        recommendation={{
          ...recommendation,
          approval_expires_at: new Date(now + 1500).toISOString(),
        }}
        onDecide={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: /^aprovar$/i }),
    ).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(2000));
    expect(
      screen.queryByRole("button", { name: /^aprovar$/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/aprovação expirou/i)).toBeInTheDocument();
  } finally {
    cleanup();
    vi.useRealTimers();
  }
});

test("removes an open edit form when permission is revoked", async () => {
  const user = userEvent.setup();
  const onDecide = vi.fn();
  const { rerender } = render(
    <RecommendationCard recommendation={recommendation} onDecide={onDecide} />,
  );
  await user.click(screen.getByRole("button", { name: /editar antes/i }));
  expect(
    screen.getByLabelText("Conteúdo que será executado"),
  ).toBeInTheDocument();
  rerender(
    <RecommendationCard
      recommendation={{ ...recommendation, can_decide: false }}
      onDecide={onDecide}
    />,
  );
  expect(
    screen.queryByLabelText("Conteúdo que será executado"),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /aprovar edição/i }),
  ).not.toBeInTheDocument();
  expect(onDecide).not.toHaveBeenCalled();
});
