import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

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
  approval_expires_at: "2026-09-03T12:00:00Z",
  intent_id: null,
  action_status: null,
  executed_action: null,
  execution_result: null,
};

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
