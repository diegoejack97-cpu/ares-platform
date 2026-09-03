const baseUrl = process.env.FAKE_CRM_SANDBOX_URL ?? "http://127.0.0.1:8010";
const apiKey = process.env.FAKE_CRM_SANDBOX_API_KEY ?? "local-sandbox-key";
const headers = { Authorization: `Bearer ${apiKey}` };
const ensure = (condition, message) => {
  if (!condition) throw new Error(message);
};

const reset = await fetch(`${baseUrl}/v1/admin/reset`, { method: "POST", headers });
ensure(reset.ok, "sandbox_reset_failed");

const health = await (await fetch(`${baseUrl}/health`)).json();
const capabilities = await (await fetch(`${baseUrl}/v1/capabilities`, { headers })).json();
const first = await (
  await fetch(`${baseUrl}/v1/deals?limit=5`, { headers })
).json();
const second = await (
  await fetch(`${baseUrl}/v1/deals?limit=5&cursor=${encodeURIComponent(first.next_cursor)}`, {
    headers,
  })
).json();

const taskHeaders = {
  ...headers,
  "Content-Type": "application/json",
  "Idempotency-Key": "m4-sandbox-task-001",
  "X-Correlation-Id": "m4-sandbox-e2e",
};
const createTask = () =>
  fetch(`${baseUrl}/v1/deals/deal-001/tasks`, {
    method: "POST",
    headers: taskHeaders,
    body: JSON.stringify({ title: "Retomar oportunidade sintética" }),
  });
const task = await (await createTask()).json();
const duplicate = await (await createTask()).json();
const rateLimit = await fetch(`${baseUrl}/v1/deals`, {
  headers: { ...headers, "X-FakeCRM-Scenario": "rate_limit" },
});
const webhook = await (
  await fetch(`${baseUrl}/v1/admin/events`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ deal_id: "deal-003", event_type: "deal.updated" }),
  })
).json();

ensure(health.synthetic === true, "sandbox_is_not_marked_synthetic");
ensure(capabilities.read_changes && capabilities.signed_webhooks, "capabilities_missing");
ensure(first.items.length === 5 && second.items.length === 5, "cursor_pagination_failed");
ensure(first.items[0].id !== second.items[0].id, "cursor_replayed_first_page");
ensure(task.duplicate === false && duplicate.duplicate === true, "idempotency_failed");
ensure(rateLimit.status === 429 && rateLimit.headers.get("retry-after") === "1", "fault_failed");
ensure(webhook.signature.startsWith("sha256="), "signed_webhook_missing");

console.log(
  JSON.stringify({
    dataset: { deals: 60, synthetic: true },
    first_deal: first.items[0].id,
    task_id: task.external_id,
    duplicate: duplicate.duplicate,
    webhook_event_id: webhook.event.provider_event_id,
    rate_limit_status: rateLimit.status,
  }),
);
console.log("M4 Sandbox aprovado: contrato HTTP, cursor, idempotência, falhas e webhook assinado.");
