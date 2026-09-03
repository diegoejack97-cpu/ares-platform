import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { createClient } from "@supabase/supabase-js";

const readEnv = (path) =>
  Object.fromEntries(
    readFileSync(path, "utf8")
      .split(/\r?\n/)
      .filter((line) => line && !line.startsWith("#"))
      .map((line) => {
        const separator = line.indexOf("=");
        return [line.slice(0, separator), line.slice(separator + 1)];
      }),
  );
const ensure = (condition, message) => {
  if (!condition) throw new Error(message);
};
const webEnv = readEnv("apps/web/.env.local");
const supabase = createClient(
  webEnv.VITE_SUPABASE_URL,
  webEnv.VITE_SUPABASE_PUBLISHABLE_KEY,
);
const { data: login, error } = await supabase.auth.signInWithPassword({
  email: "admin@ares.local",
  password: "AresLocal!2026",
});
if (error) throw error;
ensure(login.session, "login_session_missing");
const headers = {
  Authorization: `Bearer ${login.session.access_token}`,
  "Content-Type": "application/json",
};
const api = "http://127.0.0.1:8000/api/v1";
const aggregateId = `deal-m3-e2e-${randomUUID()}`;
const event = await fetch(`${api}/dev/fake-crm/events`, {
  method: "POST",
  headers,
  body: JSON.stringify({ aggregate_id: aggregateId }),
});
ensure(event.status === 202, "m3_fixture_event_failed");
const list = await (await fetch(`${api}/opportunities`, { headers })).json();
const opportunity = list.items.find((item) => item.external_id === aggregateId);
ensure(opportunity, "m3_opportunity_missing");

const createdResponse = await fetch(
  `${api}/opportunities/${opportunity.id}/recommendations`,
  { method: "POST", headers, body: JSON.stringify({ trigger: "manual" }) },
);
const created = await createdResponse.json();
ensure(createdResponse.status === 202, "m3_recommendation_failed");
const recommendationResponse = await fetch(
  `${api}/recommendations/${created.recommendation_id}`,
  { headers },
);
const recommendation = await recommendationResponse.json();
ensure(recommendation.policy_verdict === "require_approval", "m3_policy_not_applied");
ensure(recommendation.context_ref, "m3_context_ref_missing");
ensure(!("target" in recommendation.recommended_action.payload), "m3_model_target_leaked");

const stale = await fetch(`${api}/recommendations/${recommendation.id}/decide`, {
  method: "POST",
  headers,
  body: JSON.stringify({ verdict: "approved", expected_version: 99 }),
});
ensure(stale.status === 409, "m3_optimistic_conflict_missing");
const approvedResponse = await fetch(
  `${api}/recommendations/${recommendation.id}/decide`,
  {
    method: "POST",
    headers,
    body: JSON.stringify({
      verdict: "edited",
      expected_version: recommendation.version,
      edited_payload: {
        action_kind: "create_task",
        payload: { title: "Retomar contato com revisão humana" },
      },
      reason: "Ajuste E2E",
    }),
  },
);
const approved = await approvedResponse.json();
ensure(approvedResponse.ok && approved.intent_id, "m3_human_approval_failed");
let action;
for (let attempt = 0; attempt < 20; attempt += 1) {
  const actionResponse = await fetch(`${api}/actions/${approved.intent_id}`, { headers });
  action = await actionResponse.json();
  if (action.intent?.status === "succeeded") break;
  await new Promise((resolve) => setTimeout(resolve, 500));
}
ensure(action.intent.status === "succeeded", "m3_worker_execution_failed");
ensure(action.attempts.length === 1, "m3_attempt_audit_failed");
ensure(
  action.execution.target.resolved_from === recommendation.context_ref,
  "m3_opaque_target_failed",
);
ensure(
  action.execution.executed_action.payload.title ===
    "Retomar contato com revisão humana",
  "m3_executed_action_does_not_match_human_edit",
);
ensure((await fetch(`${api}/approvals`)).status === 401, "m3_api_allows_anonymous");

console.log(
  JSON.stringify({
    opportunity_id: opportunity.id,
    intervention_id: created.intervention_id,
    recommendation_id: recommendation.id,
    intent_id: approved.intent_id,
    context_ref: recommendation.context_ref,
    policy: recommendation.policy_verdict,
    action_status: action.intent.status,
  }),
);
console.log(
  "M3 E2E aprovado: recomendação + Policy + 409 + edição humana + worker + FakeCRM + auditoria.",
);
