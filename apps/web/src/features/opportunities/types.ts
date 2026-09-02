export interface ScorePart {
  value: number;
  weight: number;
  [key: string]: number;
}

export type ScoreBreakdown = Record<string, ScorePart>;

export interface OpportunityListItem {
  id: string;
  opportunity_type: string;
  state: string;
  score: number;
  priority: number;
  owner_user_id: string | null;
  sla_at: string | null;
  opened_at: string;
  updated_at: string;
  version: number;
  signal_count: number;
  primary_signal_type: string | null;
  score_version: string | null;
  score_breakdown: ScoreBreakdown;
  correlation_id: string;
  deal_id: string;
  title: string;
  external_id: string;
  external_stage: string | null;
  deal_value: number;
  currency: string;
  last_activity_at: string | null;
}

export interface OpportunityPage {
  items: OpportunityListItem[];
  next_cursor: string | null;
  source: string;
  freshness_at: string;
}

export interface Evidence {
  id: string;
  event_id: string;
  signal_type: string;
  rule_id: string;
  rule_version: string;
  severity: number;
  evidence: Record<string, unknown>;
  event_type: string;
  evidence_occurred_at: string;
  evidence_source_ref: string;
}

export interface TimelineEntry {
  id: string;
  from_state: string | null;
  to_state: string;
  reason: string;
  evidence_event_id: string | null;
  actor_type: string;
  actor_id: string | null;
  source: string;
  occurred_at: string;
}

export interface OpportunityDetail {
  opportunity: OpportunityListItem & {
    external_ref: Record<string, unknown>;
    deal_status: string;
  };
  evidence: Evidence[];
  timeline: TimelineEntry[];
  recommendation: null;
  recommendation_status: "planned_for_m3";
}

export interface ContextSnapshot {
  context_ref: string;
  snapshot_version: number;
  opportunity_state: string;
  facts: Record<string, unknown>;
  citations: Array<Record<string, string>>;
  token_estimate: number;
  content_hash: string;
  source: string;
  source_ref: string;
  captured_at: string;
  truncated: boolean;
  included_event_count: number;
  omitted_event_count: number;
  correlation_id: string;
}
