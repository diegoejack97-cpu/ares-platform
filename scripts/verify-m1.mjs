import { createHmac, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { createClient } from "@supabase/supabase-js";

function readEnv(path) {
  return Object.fromEntries(
    readFileSync(path, "utf8")
      .split(/\r?\n/)
      .filter((line) => line && !line.startsWith("#"))
      .map((line) => {
        const separator = line.indexOf("=");
        return [line.slice(0, separator), line.slice(separator + 1)];
      }),
  );
}

function ensure(condition, message) {
  if (!condition) throw new Error(message);
}

const env = readEnv(".env");
const webEnv = readEnv("apps/web/.env.local");
const supabase = createClient(webEnv.VITE_SUPABASE_URL, webEnv.VITE_SUPABASE_PUBLISHABLE_KEY);
const { data: login, error: loginError } = await supabase.auth.signInWithPassword({
  email: "admin@ares.local",
  password: "AresLocal!2026",
});
if (loginError) throw loginError;
ensure(login.session, "login_session_missing");

const providerEventId = `m1-e2e-${randomUUID()}`;
const payload = JSON.stringify({
  provider_event_id: providerEventId,
  event_type: "deal.updated",
  aggregate_type: "deal",
  aggregate_id: "deal-m1-e2e",
  occurred_at: new Date().toISOString(),
  data: { stage: "proposal", risk: "follow_up_overdue", fixture: true },
});
const signature = `sha256=${createHmac("sha256", env.ARES_FAKE_CRM_WEBHOOK_SECRET).update(payload).digest("hex")}`;
const webhookHeaders = {
  "Content-Type": "application/json",
  "X-FakeCRM-Signature": signature,
  "X-ARES-Connection-Id": "30000000-0000-0000-0000-000000000001",
};
const webhookUrl = `${webEnv.VITE_SUPABASE_URL}/functions/v1/fake-crm-webhook`;
const firstWebhook = await fetch(webhookUrl, { method: "POST", headers: webhookHeaders, body: payload });
const firstReceipt = await firstWebhook.json();
ensure(firstWebhook.status === 202, `webhook_failed_${firstWebhook.status}`);
ensure(firstReceipt.accepted && !firstReceipt.duplicate, "first_webhook_not_accepted");

const duplicateWebhook = await fetch(webhookUrl, {
  method: "POST",
  headers: webhookHeaders,
  body: payload,
});
const duplicateReceipt = await duplicateWebhook.json();
ensure(duplicateWebhook.status === 202 && duplicateReceipt.duplicate, "webhook_not_idempotent");

const tick = await fetch("http://127.0.0.1:8000/api/v1/internal/tick", {
  method: "POST",
  headers: { "X-ARES-Tick-Secret": env.ARES_TICK_SECRET },
});
const tickResult = await tick.json();
ensure(tick.ok, `tick_failed_${tick.status}`);
ensure(tickResult.acquired && tickResult.succeeded >= 1, "tick_did_not_process_job");

const anonymous = await fetch("http://127.0.0.1:8000/api/v1/journal/events");
ensure(anonymous.status === 401, "journal_allows_anonymous_access");
const journalResponse = await fetch("http://127.0.0.1:8000/api/v1/journal/events", {
  headers: { Authorization: `Bearer ${login.session.access_token}` },
});
const journal = await journalResponse.json();
ensure(journalResponse.ok, `journal_failed_${journalResponse.status}`);
const event = journal.items.find((item) => item.provider_event_id === providerEventId);
ensure(event, "webhook_event_missing_from_journal");
ensure(event.correlation_id === firstReceipt.correlation_id, "correlation_id_not_preserved");

console.log("M1 E2E aprovado: login + HMAC + inbox/job + tick + Journal + RLS.");

