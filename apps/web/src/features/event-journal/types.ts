export type JournalEvent = {
  id: string;
  provider_event_id: string;
  event_type: string;
  aggregate_type: string;
  aggregate_id: string;
  correlation_id: string;
  source: "crm";
  producer: "fake-crm";
  status: "recorded";
  occurred_at: string;
  recorded_at: string;
  data: Record<string, unknown>;
};

export type JournalPage = {
  items: JournalEvent[];
  total: number;
  source: string;
  freshness_at: string;
};
