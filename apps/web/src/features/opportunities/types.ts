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
  recommendation: Recommendation | null;
  recommendation_status: string;
}

export interface ActionDraft {
  action_kind: "create_task" | "add_note" | "update_stage";
  payload: Record<string, unknown>;
}

export interface RecommendationAlternative {
  label: string;
  action: ActionDraft;
  tradeoff: string;
}

export interface Recommendation {
  id: string;
  intervention_id: string;
  opportunity_id: string;
  correlation_id: string;
  recommended_action: ActionDraft;
  rationale: string;
  confidence: number;
  alternatives: RecommendationAlternative[];
  contraindication: string | null;
  urgency: "low" | "normal" | "high" | "critical";
  generation_mode: "agno_openai" | "deterministic_fallback";
  status: string;
  version: number;
  context_ref: string;
  policy_verdict: "allow" | "require_approval" | "deny";
  policy_set: string;
  policy_version: number;
  policy_hash: string;
  approval_id: string | null;
  approval_status: string | null;
  approval_expires_at: string | null;
  intent_id: string | null;
  action_status: string | null;
  executed_action: ActionDraft | null;
  execution_result: Record<string, unknown> | null;
}

export interface ApprovalItem extends Recommendation {
  approval_version: number;
  required_role: string;
  expires_at: string;
  created_at: string;
  title: string;
  deal_value: number;
  currency: string;
}

export interface ApprovalPage {
  items: ApprovalItem[];
  total: number;
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
