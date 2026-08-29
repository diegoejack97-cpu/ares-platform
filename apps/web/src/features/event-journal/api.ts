import type { JournalPage } from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`ARES API respondeu com status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getJournalEvents(): Promise<JournalPage> {
  return parseResponse<JournalPage>(
    await fetch(`${API_URL}/api/v1/journal/events`),
  );
}

export async function simulateFakeCRMEvent(): Promise<void> {
  const response = await fetch(`${API_URL}/api/v1/dev/fake-crm/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_type: "deal.updated" }),
  });
  await parseResponse(response);
}
