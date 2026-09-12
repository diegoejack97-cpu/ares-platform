export interface PipelineDeal {
  id: string;
  external_id: string;
  title: string;
  stage: string;
  value: number | null;
  currency: string | null;
  version: number;
  owner_id: string | null;
  changed_at: string | null;
  synthetic: boolean;
  is_missing: boolean;
}

export interface PipelineSnapshot {
  items: PipelineDeal[];
  stages: { id: string; label: string }[];
  capabilities: { update_stage: boolean; read_deals: boolean };
  permissions: { can_move: boolean; can_manage: boolean };
  freshness_at: string | null;
  source: string;
  partial: boolean;
  missing_count: number;
  next_cursor: string | null;
  connection: { id: string; provider: string; status: string } | null;
}

export interface FieldMapping {
  canonical_field: string;
  provider_path: string;
  transformation: "identity" | "uppercase";
  required: boolean;
}

export interface StageMapping {
  external_stage: string;
  canonical_stage: string;
  label: string;
  position: number;
}

export interface IntegrationMapping {
  connection: PipelineSnapshot["connection"];
  mapping: { version: number; fields: FieldMapping[]; stages: StageMapping[] };
  suggested: { fields: FieldMapping[]; stages: StageMapping[] };
}

export interface IntegrationJob {
  id: string;
  error_code?: string | null;
  status: string;
  attempts: number;
  payload: {
    mode?: string;
    records?: number;
    pages?: number;
    error_code?: string;
  };
  created_at: string;
  run_after: string;
}

export interface StageCommand {
  stage: string;
  expected_version: number;
  idempotency_key: string;
  confirmed: true;
  reason?: string;
}

export interface StageResult {
  status?: string;
  correlation_id?: string;
  duplicate?: boolean;
}
