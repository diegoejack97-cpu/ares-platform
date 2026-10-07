import type { JournalPage } from "./types";
import { supabase } from "@/lib/supabase";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`ARES API respondeu com status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getJournalEvents(cursor?: string): Promise<JournalPage> {
  const headers = await authorizationHeaders();
  const params = new URLSearchParams({ limit: "50" });
  if (cursor) params.set("cursor", cursor);
  return parseResponse<JournalPage>(
    await fetch(`${API_URL}/api/v1/journal/events?${params}`, { headers }),
  );
}

export async function simulateFakeCRMEvent(): Promise<void> {
  const authorization = await authorizationHeaders();
  const response = await fetch(`${API_URL}/api/v1/dev/fake-crm/events`, {
    method: "POST",
    headers: { ...authorization, "Content-Type": "application/json" },
    body: JSON.stringify({ event_type: "deal.updated" }),
  });
  await parseResponse(response);
}

async function authorizationHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new Error("Sessão ARES ausente");
  return { Authorization: `Bearer ${data.session.access_token}` };
}
