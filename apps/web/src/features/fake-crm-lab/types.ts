export interface FakeCRMCapabilities {
  read_deals: boolean;
  describe_schema: boolean;
  read_changes: boolean;
  create_task: boolean;
  add_note: boolean;
  update_stage: boolean;
  signed_webhooks: boolean;
}

export interface FakeCRMStage {
  id: string;
  label: string;
}

export interface FakeCRMDeal {
  id: string;
  title: string;
  stage: string;
  value: number;
  currency: string;
  version: number;
  changed_at: string;
  owner_id: string | null;
  company_id: string;
  contact_id: string;
  synthetic: true;
  scenario: string;
}

export interface FakeCRMLabSnapshot {
  health: { status: string; service: string; synthetic: boolean };
  capabilities: FakeCRMCapabilities;
  stages: FakeCRMStage[];
  deals: FakeCRMDeal[];
  counts: {
    companies: number;
    contacts: number;
    deals: number;
    activities: number;
    tasks: number;
    notes: number;
  };
  watermark: string | null;
  freshness_at: string;
  source: string;
  docs_url: string;
}

export interface FakeCRMFaultResult {
  scenario: string;
  observed: boolean;
  status_code: number | null;
  code: string;
  retry_after: string | null;
}
