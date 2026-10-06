import { test } from "node:test";
import assert from "node:assert/strict";
import { selectWebhookSecret } from "./connection-secret.ts";

test("each connection selects only its own company's server secret", () => {
  const values: Record<string, string> = {
    ARES_ENVIRONMENT: "demonstration",
    ARES_CRM_CONNECTIONS: JSON.stringify({
      companyA: { connection_id: "a", webhook_secret_env: "ARES_CRM_SECRET_A" },
      companyB: { connection_id: "b", webhook_secret_env: "ARES_CRM_SECRET_B" },
    }),
    ARES_CRM_SECRET_A: "a".repeat(32),
    ARES_CRM_SECRET_B: "b".repeat(32),
    FAKE_CRM_WEBHOOK_SECRET: "shared-legacy-key",
  };
  const env = (key: string) => values[key];
  assert.equal(selectWebhookSecret("a", env)?.tenantId, "companyA");
  assert.equal(selectWebhookSecret("b", env)?.secret, values.ARES_CRM_SECRET_B);
  assert.equal(selectWebhookSecret("unknown", env), null);
  delete values.ARES_CRM_SECRET_B;
  assert.equal(selectWebhookSecret("b", env), null);
});
