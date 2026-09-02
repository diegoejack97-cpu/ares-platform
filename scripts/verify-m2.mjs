import { createHmac, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { createClient } from "@supabase/supabase-js";

const readEnv = (path) => Object.fromEntries(readFileSync(path, "utf8").split(/\r?\n/).filter((line) => line && !line.startsWith("#")).map((line) => { const separator = line.indexOf("="); return [line.slice(0, separator), line.slice(separator + 1)]; }));
const ensure = (condition, message) => { if (!condition) throw new Error(message); };
const env = readEnv(".env");
const webEnv = readEnv("apps/web/.env.local");
const supabase = createClient(webEnv.VITE_SUPABASE_URL, webEnv.VITE_SUPABASE_PUBLISHABLE_KEY);
const { data: login, error } = await supabase.auth.signInWithPassword({ email: "admin@ares.local", password: "AresLocal!2026" });
if (error) throw error;
ensure(login.session, "login_session_missing");
const authorization = { Authorization: `Bearer ${login.session.access_token}` };
const now = new Date();
const externalId = `deal-m2-e2e-${randomUUID()}`;
const providerEventId = `m2-e2e-${randomUUID()}`;
const payload = JSON.stringify({
  provider_event_id: providerEventId, event_type: "deal.updated", aggregate_type: "deal",
  aggregate_id: externalId, occurred_at: now.toISOString(), data: {
    title: "Recuperação M2 E2E", stage: "proposal", previous_stage: "negotiation", status: "open",
    risk: "follow_up_overdue", next_follow_up_at: new Date(now.getTime() - 172800000).toISOString(),
    days_in_stage: 12, next_step: null, owner_id: null, value: 125000, currency: "BRL",
    days_since_contact: 14, expected_close_at: new Date(now.getTime() + 259200000).toISOString(), fixture: true,
  },
});
const signature = `sha256=${createHmac("sha256", env.ARES_FAKE_CRM_WEBHOOK_SECRET).update(payload).digest("hex")}`;
const webhookHeaders = { "Content-Type": "application/json", "X-FakeCRM-Signature": signature, "X-ARES-Connection-Id": "30000000-0000-0000-0000-000000000001" };
const webhookUrl = `${webEnv.VITE_SUPABASE_URL}/functions/v1/fake-crm-webhook`;
const first = await fetch(webhookUrl, { method: "POST", headers: webhookHeaders, body: payload });
const firstBody = await first.json();
ensure(first.status === 202 && !firstBody.duplicate, "m2_webhook_not_accepted");
const duplicate = await fetch(webhookUrl, { method: "POST", headers: webhookHeaders, body: payload });
ensure(duplicate.status === 202 && (await duplicate.json()).duplicate, "m2_webhook_not_idempotent");
const tick = await fetch("http://127.0.0.1:8000/api/v1/internal/tick", { method: "POST", headers: { "X-ARES-Tick-Secret": env.ARES_TICK_SECRET } });
const tickBody = await tick.json();
ensure(tick.ok && tickBody.succeeded >= 1, "m2_tick_failed");
const listResponse = await fetch("http://127.0.0.1:8000/api/v1/opportunities?min_score=0.8", { headers: authorization });
const list = await listResponse.json();
const opportunity = list.items.find((item) => item.external_id === externalId);
ensure(listResponse.ok && opportunity, "m2_opportunity_missing");
ensure(opportunity.signal_count === 8 && opportunity.score_version === "m2.1", "m2_signal_or_score_contract_failed");
ensure(Object.keys(opportunity.score_breakdown).length === 4, "m2_score_breakdown_missing");
const detailResponse = await fetch(`http://127.0.0.1:8000/api/v1/opportunities/${opportunity.id}`, { headers: authorization });
const detail = await detailResponse.json();
ensure(detailResponse.ok && detail.evidence.length === 8 && detail.timeline.length === 2, "m2_detail_audit_chain_failed");
ensure(detail.recommendation === null && detail.recommendation_status === "planned_for_m3", "m3_boundary_broken");
const contextResponse = await fetch(`http://127.0.0.1:8000/api/v1/opportunities/${opportunity.id}/context`, { headers: authorization });
const context = await contextResponse.json();
ensure(contextResponse.ok && context.token_estimate <= 2500 && context.citations.length >= 1 && context.content_hash.length === 64, "m2_context_contract_failed");
ensure((await fetch("http://127.0.0.1:8000/api/v1/opportunities")).status === 401, "m2_api_allows_anonymous");
console.log(JSON.stringify({ event: firstBody.event_id, opportunity: opportunity.id, signals: detail.evidence.length, score: opportunity.score, context_ref: context.context_ref, token_estimate: context.token_estimate }));
console.log("M2 E2E aprovado: webhook + tick + 8 sinais + score + oportunidade + contexto + APIs.");
