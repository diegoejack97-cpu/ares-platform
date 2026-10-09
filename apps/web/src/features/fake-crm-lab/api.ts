import { supabase } from "@/lib/supabase";

import type { FakeCRMFaultResult, FakeCRMLabSnapshot } from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH";
  body?: unknown;
  idempotencyKey?: string;
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new Error("Sessão ARES ausente");
  const response = await fetch(`${API_URL}${path}`, {
    method: options.method ?? "GET",
    headers: {
      Authorization: `Bearer ${data.session.access_token}`,
      "Content-Type": "application/json",
      ...(options.idempotencyKey
        ? { "Idempotency-Key": options.idempotencyKey }
        : {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string | { code?: string };
    } | null;
    const code =
      typeof payload?.detail === "string"
        ? payload.detail
        : payload?.detail?.code;
    throw new Error(code ?? `ARES API respondeu com status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getFakeCRMLabSnapshot(): Promise<FakeCRMLabSnapshot> {
  return request("/api/v1/dev/fake-crm/lab");
}

export function resetFakeCRMLab(): Promise<unknown> {
  return request("/api/v1/dev/fake-crm/lab/reset", { method: "POST" });
}

export function createFakeCRMTask(
  dealId: string,
  title: string,
): Promise<unknown> {
  return request(`/api/v1/dev/fake-crm/lab/deals/${dealId}/tasks`, {
    method: "POST",
    body: { title },
    idempotencyKey: crypto.randomUUID(),
  });
}

export function addFakeCRMNote(dealId: string, body: string): Promise<unknown> {
  return request(`/api/v1/dev/fake-crm/lab/deals/${dealId}/notes`, {
    method: "POST",
    body: { body },
    idempotencyKey: crypto.randomUUID(),
  });
}

export function updateFakeCRMStage(
  dealId: string,
  stage: string,
  expectedVersion: number,
): Promise<unknown> {
  return request(`/api/v1/dev/fake-crm/lab/deals/${dealId}/stage`, {
    method: "PATCH",
    body: { stage, expected_version: expectedVersion },
    idempotencyKey: crypto.randomUUID(),
  });
}

export function sendFakeCRMEvent(dealId: string): Promise<unknown> {
  return request(`/api/v1/dev/fake-crm/lab/deals/${dealId}/events`, {
    method: "POST",
  });
}

export function testFakeCRMFault(
  scenario: string,
): Promise<FakeCRMFaultResult> {
  return request(`/api/v1/dev/fake-crm/lab/faults/${scenario}`, {
    method: "POST",
  });
}
