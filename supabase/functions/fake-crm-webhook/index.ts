import { createClient } from "@supabase/supabase-js";
import { selectWebhookSecret } from "./connection-secret.ts";

const MAX_BODY_BYTES = 1_048_576;

function json(body: unknown, status: number): Response {
  return Response.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

function hex(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

async function hmacSha256(secret: string, body: Uint8Array): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return hex(await crypto.subtle.sign("HMAC", key, body));
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let mismatch = 0;
  for (let index = 0; index < left.length; index += 1) {
    mismatch |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return mismatch === 0;
}

Deno.serve(async (request) => {
  if (request.method !== "POST") {
    return json({ code: "METHOD_NOT_ALLOWED" }, 405);
  }

  const declaredLength = Number(request.headers.get("content-length") ?? 0);
  if (declaredLength > MAX_BODY_BYTES) {
    return json({ code: "PAYLOAD_TOO_LARGE" }, 413);
  }

  const connectionId = request.headers.get("x-ares-connection-id");
  if (!connectionId) return json({ code: "MISSING_CONNECTION" }, 422);
  let scopedSecret: ReturnType<typeof selectWebhookSecret>;
  try {
    scopedSecret = selectWebhookSecret(connectionId, (key) =>
      Deno.env.get(key),
    );
  } catch {
    return json({ code: "FUNCTION_MISCONFIGURED" }, 500);
  }
  if (!scopedSecret) return json({ code: "UNKNOWN_CONNECTION" }, 404);
  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !serviceRoleKey) {
    return json({ code: "FUNCTION_MISCONFIGURED" }, 500);
  }

  const rawBody = new Uint8Array(await request.arrayBuffer());
  if (rawBody.byteLength > MAX_BODY_BYTES) {
    return json({ code: "PAYLOAD_TOO_LARGE" }, 413);
  }

  const providedSignature = request.headers
    .get("x-fakecrm-signature")
    ?.replace(/^sha256=/, "");
  const expectedSignature = await hmacSha256(scopedSecret.secret, rawBody);
  if (
    !providedSignature ||
    !constantTimeEqual(providedSignature, expectedSignature)
  ) {
    return json({ code: "INVALID_SIGNATURE" }, 401);
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(new TextDecoder().decode(rawBody));
  } catch {
    return json({ code: "INVALID_JSON" }, 422);
  }

  const providerEventId = String(payload.provider_event_id ?? "");
  if (!providerEventId) {
    return json({ code: "MISSING_PROVIDER_EVENT_ID" }, 422);
  }

  const admin = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data: connection, error: connectionError } = await admin
    .from("connections")
    .select("id, tenant_id")
    .eq("id", connectionId)
    .eq("tenant_id", scopedSecret.tenantId)
    .in("provider", ["fake-crm", "fake-crm-http"])
    .neq("status", "revoked")
    .single();

  if (connectionError || !connection) {
    return json({ code: "UNKNOWN_CONNECTION" }, 404);
  }

  const correlationId = crypto.randomUUID();
  const receivedAt = new Date();
  const objectPath = [
    connection.tenant_id,
    connection.id,
    receivedAt.toISOString().slice(0, 10),
    `${correlationId}.json`,
  ].join("/");

  const { error: uploadError } = await admin.storage
    .from("webhook-raw")
    .upload(objectPath, rawBody, {
      contentType: "application/json",
      upsert: false,
    });
  if (uploadError) {
    return json(
      { code: "RAW_PAYLOAD_STORAGE_FAILED", correlation_id: correlationId },
      500,
    );
  }

  const payloadHash = hex(await crypto.subtle.digest("SHA-256", rawBody));
  const { data: receipt, error: receiptError } = await admin
    .from("webhook_receipts")
    .insert({
      tenant_id: connection.tenant_id,
      connection_id: connection.id,
      provider_event_id: providerEventId,
      payload_hash: payloadHash,
      headers_redacted: {
        content_type: request.headers.get("content-type"),
        user_agent: request.headers.get("user-agent"),
      },
      raw_payload_ref: `webhook-raw/${objectPath}`,
      status: "queued",
      correlation_id: correlationId,
    })
    .select("id")
    .single();

  if (receiptError?.code === "23505") {
    return json(
      { accepted: true, duplicate: true, correlation_id: correlationId },
      202,
    );
  }
  if (receiptError || !receipt) {
    return json(
      { code: "RECEIPT_PERSIST_FAILED", correlation_id: correlationId },
      500,
    );
  }

  const { error: jobError } = await admin.from("jobs").insert({
    tenant_id: connection.tenant_id,
    kind: "webhook.normalize",
    payload_version: 1,
    payload: { receipt_id: receipt.id },
    status: "queued",
    correlation_id: correlationId,
  });
  if (jobError) {
    return json(
      { code: "JOB_ENQUEUE_FAILED", correlation_id: correlationId },
      500,
    );
  }

  return json(
    {
      accepted: true,
      duplicate: false,
      receipt_id: receipt.id,
      correlation_id: correlationId,
    },
    202,
  );
});
